"""Stage-composer CLI — the .bat's replacement for the additive robocopy /E.

``build_installer_premium.bat`` no longer stages with an additive ``robocopy /E``
(which let stale/deleted files survive). It calls this wrapper, which assembles
the input and BUILD_RECEIPT paths and runs the transactional composer
(:mod:`scripts.release.stage_composer`) to produce a clean, sealed premium_stage.

The heavy materialize/sign steps are injected so the policy is testable without a
multi-GB build; ``main`` wires the real ones (HF-symlink materialization + inner
EXE signing in signed mode).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from scripts.release import asset_bootstrap, installer_gate, signing_gate, stage_composer

# Declarative dead weight dropped from every stage (leftover whisper.cpp model
# from the abandoned Rust-native STT path — referenced nowhere in shipped code).
DEAD_WEIGHT = ["models/ggml-base.bin"]

Materializer = Callable[[Path], None]
Signer = Callable[[Path, str], None]


def input_paths(repo: Path, dist_premium: Path, tauri_release: Path) -> dict[str, Path]:
    sot, assets_manifest = asset_bootstrap.sot_paths(dist_premium)
    return {
        "backend": dist_premium / "kali-backend",
        "desktop_exe": tauri_release / "kali-desktop.exe",
        "assets": sot,
        "assets_manifest": assets_manifest,  # G5: SoT integrity verified before copy
        "webview2": repo / "scripts" / "install-webview2.ps1",
    }


def receipt_paths(dist_premium: Path, tauri_release: Path) -> dict[str, Path]:
    return {
        "backend": dist_premium / "kali-backend.BUILD_RECEIPT.json",
        "desktop": tauri_release / "kali-desktop.exe.BUILD_RECEIPT.json",
    }


def compose(repo: Path, dist_premium: Path, tauri_release: Path, *, mode: str,
            version: str, git_sha: str, materializer: Materializer, signer: Signer,
            token: str = "1") -> Path:
    """Assemble inputs/receipts and run the transactional composer."""
    return stage_composer.compose_stage(
        dist_premium,
        inputs=input_paths(repo, dist_premium, tauri_release),
        receipts=receipt_paths(dist_premium, tauri_release),
        version=version, git_sha=git_sha, mode=mode, exclusions=DEAD_WEIGHT,
        materializer=materializer, signer=signer, token=token,
    )


def _real_materializer(stage: Path) -> None:
    from scripts.materialize_hf_symlinks import materialize_symlinks
    materialize_symlinks(stage)


def _resolve_signtool(env: dict[str, str]) -> str | None:
    import shutil
    return env.get("KALI_SIGN_SIGNTOOL") or shutil.which("signtool") or shutil.which("signtool.exe")


def build_signing(mode: str, *, env: dict[str, str]) -> Signer:
    """Build the inner-EXE signer from a VALIDATED, owner-supplied env contract.

    For a signed build this runs the fail-closed preflight up front (so it aborts
    BEFORE any stage mutation): exactly one selector (PFX xor store/HSM thumbprint),
    a signtool, and an expected signer thumbprint. Internal builds get a no-op."""
    if mode != "signed":
        return lambda stage, m: None
    selector = signing_gate.resolve_selector(
        pfx=env.get("KALI_SIGN_PFX"), pfx_pass=env.get("KALI_SIGN_PFX_PASS"),
        thumbprint=env.get("KALI_SIGN_THUMBPRINT"))
    signtool = _resolve_signtool(env)
    expected_thumbprint = env.get("KALI_SIGN_EXPECTED_THUMBPRINT", "")
    timestamp_url = env.get("KALI_SIGN_TR_URL", "http://timestamp.digicert.com")
    signing_gate.preflight("signed", selector=selector, signtool=signtool,
                           expected_thumbprint=expected_thumbprint)

    def _sign(stage: Path, m: str) -> None:
        for exe in (stage / "kali-desktop.exe", stage / "kali-backend" / "kali-backend.exe"):
            proc = subprocess.run(signing_gate.build_sign_command(
                exe, selector=selector, timestamp_url=timestamp_url, signtool=signtool),
                capture_output=True, text=True)
            if proc.returncode != 0:
                raise signing_gate.SigningGateError(
                    f"inner sign failed: {exe}: {proc.stderr[:200]}")
            signing_gate.verify_signed(exe, expected_thumbprint=expected_thumbprint,
                                       inspector=signing_gate.powershell_inspector)
    return _sign


def main(argv: list[str] | None = None) -> int:
    """Live entrypoint (wired from the .bat). Requires a validated mode + receipts."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3:
        print("usage: compose_cli <mode> <version> <git_sha>", file=sys.stderr)
        return 2
    mode, version, git_sha = args[0], args[1], args[2]
    repo = Path(__file__).resolve().parents[2]
    dist = repo / "dist_premium"
    tauri = repo / "src-tauri" / "target" / "release"
    status = repo / "release-status.json"
    mode = installer_gate.resolve_build_mode(
        mode, distributable=installer_gate.read_distributable(status)
    )
    signer = build_signing(mode, env=dict(os.environ))  # preflight BEFORE compose
    stage = compose(repo, dist, tauri, mode=mode, version=version, git_sha=git_sha,
                    materializer=_real_materializer, signer=signer)
    print(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
