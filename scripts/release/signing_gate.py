"""Fail-closed Windows code-signing policy (C4, OPUS-201).

A distributable release must carry a trusted Authenticode signature or the build
must fail. This module holds the *policy* (pure, unit-tested with an injected
command runner — no real signtool/cert needed):

* **mode** — every build declares ``signed`` or ``internal`` explicitly; a
  missing/unknown mode is refused (there is NO default release mode).
* **selector** — exactly one credential source: a PFX file OR a Windows
  certificate-store / HSM thumbprint (both or neither is refused).
* **preflight** — in ``signed`` mode, refuse up front unless a selector, a
  signtool and an expected signer identity are all present.
* **sign** — SHA256 file digest + an RFC3161 SHA256 timestamp.
* **verify** — ``signtool verify /pa`` must succeed AND the output must show the
  expected signer AND a timestamp; anything else raises.
* **internal marker** — an unsigned build is renamed to an explicit
  ``…-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE`` artifact with a marker file.

The actual EV/OV certificate stays an owner gate; its absence does not weaken any
check here — it only means a distributable ``signed`` build cannot be produced.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

MODES = ("signed", "internal")
INTERNAL_SUFFIX = "-INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE"
INTERNAL_MARKER = "INTERNAL-UNSIGNED.txt"

# runner(cmd) -> (returncode, combined_output)
Runner = Callable[[list[str]], "tuple[int, str]"]


class SigningGateError(Exception):
    """A signing-policy violation (fail-closed)."""


def parse_mode(arg: Any) -> str:
    """Return the explicit build mode; refuse a missing/unknown one (no default)."""
    if arg not in MODES:
        raise SigningGateError(
            f"MODE: build mode must be exactly 'signed' or 'internal', got {arg!r}"
        )
    return arg


def require_signing(mode: str) -> bool:
    """Signed builds must sign; internal builds must not be published."""
    return mode == "signed"


def resolve_selector(*, pfx: str | None, pfx_pass: str | None,
                     thumbprint: str | None) -> dict[str, Any]:
    """Exactly one credential: a PFX file OR a store/HSM thumbprint."""
    if bool(pfx) == bool(thumbprint):
        raise SigningGateError(
            "SELECTOR: exactly one of PFX or store/HSM thumbprint is required"
        )
    if pfx:
        return {"kind": "pfx", "pfx": pfx, "pass": pfx_pass}
    return {"kind": "thumbprint", "thumbprint": thumbprint}


def preflight(mode: str, *, selector: dict[str, Any] | None, signtool: str | None,
              expected_thumbprint: str | None) -> None:
    """Fail-closed pre-build check: an internal build needs nothing; a signed build
    refuses unless selector + signtool + expected signer THUMBPRINT are all present."""
    if not require_signing(mode):
        return
    if selector is None:
        raise SigningGateError("SELECTOR: signed build requires a signing selector")
    if not signtool:
        raise SigningGateError("SIGNTOOL: signed build requires signtool.exe")
    if not expected_thumbprint:
        raise SigningGateError("SIGNER: signed build requires an expected signer thumbprint")


def build_sign_command(file: Path, *, selector: dict[str, Any], timestamp_url: str,
                       signtool: str) -> list[str]:
    """signtool sign with SHA256 digest + RFC3161 SHA256 timestamp + selector."""
    cmd = [signtool, "sign", "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256"]
    if selector["kind"] == "pfx":
        cmd += ["/f", selector["pfx"]]
        if selector.get("pass"):
            cmd += ["/p", selector["pass"]]
    else:
        cmd += ["/sha1", selector["thumbprint"]]
    cmd.append(str(file))
    return cmd


def _inspect_command(file: Path, *, powershell: str = "powershell") -> list[str]:
    """PowerShell Get-AuthenticodeSignature as STRUCTURED JSON (no substring parsing)."""
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{file}'; "
        "[pscustomobject]@{ Status = [string]$s.Status; "
        "Thumbprint = if ($s.SignerCertificate) { $s.SignerCertificate.Thumbprint } else { '' }; "
        "Timestamped = [bool]$s.TimeStamperCertificate } | ConvertTo-Json -Compress"
    )
    return [powershell, "-NoProfile", "-NonInteractive", "-Command", script]


def inspect_signature(file: Path, *, runner: Runner) -> dict[str, Any]:
    """Structured Authenticode report: {status, thumbprint (upper), timestamped}."""
    import json
    rc, out = runner(_inspect_command(file))
    if rc != 0:
        raise SigningGateError(f"SIGN_INSPECT_FAILED: rc={rc}: {out[:200]}")
    try:
        data = json.loads(out)
    except (ValueError, TypeError) as e:
        raise SigningGateError(f"SIGN_INSPECT_MALFORMED: {out[:120]!r}") from e
    return {
        "status": str(data.get("Status", "")),
        "thumbprint": str(data.get("Thumbprint") or "").upper(),
        "timestamped": bool(data.get("Timestamped")),
    }


Inspector = Callable[[Path], "dict[str, Any]"]


def verify_signed(file: Path, *, expected_thumbprint: str, inspector: Inspector) -> None:
    """Fail-closed structured verify: Status==Valid, EXACT signer thumbprint, timestamp."""
    report = inspector(file)
    if report.get("status") != "Valid":
        raise SigningGateError(f"SIGN_VERIFY_FAILED: Authenticode status={report.get('status')!r}")
    if report.get("thumbprint", "").upper() != expected_thumbprint.upper():
        raise SigningGateError(
            f"WRONG_SIGNER: thumbprint {report.get('thumbprint')!r} != expected")
    if not report.get("timestamped"):
        raise SigningGateError("NO_TIMESTAMP: signature is not RFC3161-timestamped")


def powershell_inspector(file: Path) -> dict[str, Any]:
    """Production inspector — runs PowerShell Get-AuthenticodeSignature."""
    import subprocess

    def _runner(cmd: list[str]) -> tuple[int, str]:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout
    return inspect_signature(file, runner=_runner)


def write_internal_marker(directory: Path, *, version: str) -> Path:
    """Drop the INTERNAL-UNSIGNED marker (naming is done by ISCC OutputBaseFilename;
    there is no post-build EXE rename)."""
    marker = directory / INTERNAL_MARKER
    marker.write_text(
        f"INTERNAL-UNSIGNED build of KALI Premium {version}.\n"
        "DO-NOT-DISTRIBUTE: this artifact is UNSIGNED and is for local, "
        "trusted-alpha verification only. A public release requires a trusted "
        "Authenticode code-signing identity.\n",
        encoding="utf-8",
    )
    return marker
