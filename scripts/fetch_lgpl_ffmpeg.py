"""Fetch + install the LGPL FFmpeg shared DLLs for the Premium bundle.

The desktop bundle's `models/ffmpeg/` DLLs are loaded by torchcodec (which
F5-TTS uses via `torchaudio.load` to decode the reference WAV). The default
public FFmpeg Windows builds are **GPLv3** (`--enable-gpl` + libx264) — illegal
to ship inside a proprietary installer. F5 only DECODES audio (libx264 is an
encoder, never used), so an **LGPL** build (no `--enable-gpl`/x264/x265) fully
satisfies torchcodec while removing the copyleft conflict (P1.4).

This installs the BtbN `win64-lgpl-shared` build (FFmpeg 8.1 — matching the
bundle's avcodec-62/avformat-62/avutil-60 sonames), verifies the bundled
LICENSE is LGPL (not GPL), and drops it alongside the DLLs so the installer
ships the required license text.

H1.2: the DLLs are installed into the ONE shipping source-of-truth —
``dist_premium/premium_assets/models/ffmpeg`` — and the SoT integrity manifest is
re-sealed afterwards. The backend build reads the same directory, so the bytes
swapped into ``av.libs`` and the bytes staged into the installer can no longer be
two different truths.

Usage:
    python scripts/fetch_lgpl_ffmpeg.py                    # install into the SoT
    python scripts/fetch_lgpl_ffmpeg.py --dist D:\\alt\\dist_premium
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.release import asset_bootstrap, stage_policy  # noqa: E402

# H1.1: an immutable, owner-pinned release asset. The tag is a dated BtbN autobuild
# (never the mutable "latest" release) and the download is verified against the
# SHA256 GitHub reports for that exact asset. An empty ASSET_SHA256 fails closed
# (refuses to install unverified bytes). Bump tag + name + SHA256 together.
FFMPEG_TAG = "autobuild-2026-07-24-13-32"
ASSET_NAME = "ffmpeg-n8.1.2-31-g8c9502e9b0-win64-lgpl-shared-8.1.zip"
ASSET_URL = (
    f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{FFMPEG_TAG}/{ASSET_NAME}"
)
ASSET_SHA256 = "8271471492f5ebe8ccf15a39fbdac4266db4832a4765ba5603b49da36aef2f36"


def verify_download_sha256(path: Path, expected: str) -> None:
    """Fail-closed integrity gate for the downloaded asset (no mutable trust)."""
    if not expected:
        raise SystemExit(
            "ASSET_SHA256 is not pinned — refusing to install unverified FFmpeg bytes")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    actual = h.hexdigest()
    if actual != expected.lower():
        raise SystemExit(f"FFmpeg SHA256 mismatch: {actual} != pinned {expected}")
# The exact soname set the bundle (and torchcodec) expects — FFmpeg 8.x.
EXPECTED_DLLS = {
    "avcodec-62.dll",
    "avdevice-62.dll",
    "avfilter-11.dll",
    "avformat-62.dll",
    "avutil-60.dll",
    "swresample-6.dll",
    "swscale-9.dll",
}


def _verify_lgpl(license_path: Path) -> None:
    """Raise if the bundled license is not LGPL (guards against a GPL build)."""
    text = license_path.read_text(encoding="utf-8", errors="replace")
    if "LESSER GENERAL PUBLIC LICENSE" not in text:
        raise SystemExit(f"LICENSE is not LGPL — refusing: {license_path}")
    # A pure-GPL build's LICENSE leads with the (non-lesser) GPL header.
    if text.lstrip().startswith("GNU GENERAL PUBLIC LICENSE"):
        raise SystemExit(f"LICENSE looks like full GPL — refusing: {license_path}")


OWNED_FILES = frozenset(EXPECTED_DLLS | {"LICENSE.txt"})


def assert_exact_ffmpeg_subtree(tree: Path) -> None:
    """The owned subtree must be EXACTLY the LGPL set (H6-2).

    Additive copying let a stale ``libx264``, a previous soname or any stray DLL
    survive an FFmpeg bump and ship inside models/ffmpeg — which the installed app
    puts on its DLL search path."""
    stage_policy.assert_tree_reparse_free(tree)  # no links, no dangling targets
    names = {p.name for p in tree.iterdir()}
    gpl = sorted(n for n in names if "x264" in n.lower() or "x265" in n.lower())
    if gpl:
        raise SystemExit(f"FFMPEG_SUBTREE_GPL: forbidden codecs in {tree}: {gpl}")
    extra = sorted(names - OWNED_FILES)
    missing = sorted(OWNED_FILES - names)
    if extra or missing:
        raise SystemExit(f"FFMPEG_SUBTREE_INEXACT: {tree}: extra={extra} missing={missing}")


def _stage_exact_subtree(build_dir: Path, work: Path) -> None:
    """Assemble the exact LGPL set in a clean scratch dir OUTSIDE the hashed tree."""
    bin_dir = build_dir / "bin"
    found = {p.name for p in bin_dir.glob("*.dll")} if bin_dir.is_dir() else set()
    missing = EXPECTED_DLLS - found
    if missing:
        raise SystemExit(f"LGPL build missing expected DLLs: {sorted(missing)}")
    work.mkdir(parents=True)
    for name in sorted(EXPECTED_DLLS):
        shutil.copy2(bin_dir / name, work / name)
    shutil.copy2(build_dir / "LICENSE.txt", work / "LICENSE.txt")


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_JOURNAL_NAME = "ffmpeg.journal.json"
_PHASES = ("prepare", "backed_up", "promoted", "sealed")


def _scratch(dist_premium: Path) -> Path:
    """Transaction scratch space — a SIBLING of models/, never inside the hashed tree."""
    return dist_premium / "premium_assets"


def _journal_path(dist_premium: Path) -> Path:
    return _scratch(dist_premium) / _JOURNAL_NAME


def _derived(dist_premium: Path, token: str) -> tuple[Path, Path, Path]:
    """(work, backup, target) DERIVED from a validated token — never read from disk."""
    if not _TOKEN_RE.match(token):
        raise SystemExit(f"FFMPEG_TXN_TOKEN: refusing unsafe transaction token {token!r}")
    scratch = _scratch(dist_premium)
    return (scratch / f"ffmpeg.next-{token}", scratch / f"ffmpeg.backup-{token}",
            install_target(dist_premium))


def _write_journal(dist_premium: Path, phase: str, token: str) -> None:
    asset_bootstrap.write_manifest_atomic(
        _journal_path(dist_premium), {"schema": 1, "phase": phase, "token": token})


def recover_ffmpeg_transaction(dist_premium: Path) -> str:
    """Finish or roll back an interrupted FFmpeg subtree transaction (H7-3).

    Runs BEFORE any new operation. ``sealed`` is only ever written after the new state
    was proven, and recovery RE-PROVES it anyway before dropping the backup; every
    earlier phase rolls back to last-good, restoring the old subtree AND the old manifest
    (raw bytes) together. Nothing is deleted on an unreadable journal."""
    journal = _journal_path(dist_premium)
    if not journal.is_file():
        return "nothing"
    try:
        state = json.loads(journal.read_text(encoding="utf-8"))
        phase, token = state["phase"], state["token"]
        schema = state["schema"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        raise SystemExit(f"FFMPEG_TXN_JOURNAL: unreadable journal (fail-closed): {e}") from e
    if schema != 1 or phase not in _PHASES or not isinstance(token, str):
        raise SystemExit(f"FFMPEG_TXN_JOURNAL: unknown journal state {state!r}")
    work, backup, target = _derived(dist_premium, token)
    sot, manifest_path = asset_bootstrap.sot_paths(dist_premium)
    manifest_backup = manifest_path.with_name(manifest_path.name + f".backup-{token}")
    new_state_ok = False
    if phase == "sealed":
        # "sealed" says the manifest was WRITTEN, not that the result is sound. Prove the
        # new state before keeping it — a crash can land between the write and the check,
        # and blindly keeping it would bless a subtree nobody ever verified.
        try:
            asset_bootstrap.verify_sot_integrity(sot, manifest_path)
            new_state_ok = True
        except asset_bootstrap.BootstrapError:
            new_state_ok = False
    if new_state_ok:
        shutil.rmtree(backup, ignore_errors=True)
        manifest_backup.unlink(missing_ok=True)
        action = "kept_new"
    else:
        # prepare / backed_up / promoted: roll the tree back to last-good AND put the
        # manifest back with it. The manifest is written before the journal reaches
        # "sealed", so a crash in that window would otherwise leave a NEW manifest
        # describing a subtree recovery just rolled BACK — matching neither side.
        shutil.rmtree(work, ignore_errors=True)
        if backup.is_dir():
            if target.exists():
                shutil.rmtree(target)
            os.rename(backup, target)
            action = "restored_backup"
        else:
            action = "nothing_to_restore"
        if manifest_backup.is_file():
            os.replace(manifest_backup, manifest_path)
    journal.unlink()
    return action


def replace_owned_subtree(build_dir: Path, dist_premium: Path, *, token: str = "1",
                          crash_hook: Callable[[str], None] | None = None) -> Path:
    """Crash-safe transactional replacement of models/ffmpeg (H7-3).

    Journalled at every window; the backup survives until the caller has sealed AND
    verified the new manifest, so an interruption anywhere leaves the next run able to
    restore last-good. ``crash_hook`` is a test seam fired right after each journal
    write so a child process can die exactly inside a chosen window."""
    work, backup, target = _derived(dist_premium, token)
    for leftover in (work, backup):
        if leftover.exists():
            shutil.rmtree(leftover)
    _stage_exact_subtree(build_dir, work)
    assert_exact_ffmpeg_subtree(work)

    def _mark(phase: str) -> None:
        _write_journal(dist_premium, phase, token)
        if crash_hook is not None:
            crash_hook(phase)

    _mark("prepare")
    promoted = False
    try:
        if target.exists():
            os.rename(target, backup)
        _mark("backed_up")
        os.rename(work, target)
        promoted = True
        _mark("promoted")
        assert_exact_ffmpeg_subtree(target)
    except BaseException:
        if promoted and target.exists():
            shutil.rmtree(target)
        if backup.is_dir() and not target.exists():
            os.rename(backup, target)  # restore the last-good subtree
        shutil.rmtree(work, ignore_errors=True)
        _journal_path(dist_premium).unlink(missing_ok=True)
        raise
    print(f"Replaced models/ffmpeg with the exact LGPL set -> {target}")
    return target


def _finish_transaction(dist_premium: Path, token: str,
                        crash_hook: Callable[[str], None] | None = None) -> None:
    """Seal the new manifest, prove it, and only THEN drop the backups.

    The OLD manifest is copied aside atomically BEFORE the re-seal, so the window
    between "manifest written" and journal="sealed" is recoverable: recovery restores
    the old subtree and the old manifest together."""
    _work, backup, _target = _derived(dist_premium, token)
    sot, manifest = asset_bootstrap.sot_paths(dist_premium)
    manifest_backup = manifest.with_name(manifest.name + f".backup-{token}")
    # RAW bytes: the stage pins the digest of these exact bytes, so a re-serialized
    # backup would restore equal data that no longer matches the pin.
    asset_bootstrap.write_bytes_atomic(manifest_backup, manifest.read_bytes())
    asset_bootstrap.refresh_asset_manifest(dist_premium, owned=OWNED_SUBTREE, _held=True)
    if crash_hook is not None:
        crash_hook("manifest_written")  # the window this backup exists for
    # "sealed" is written ONLY AFTER the new state is proven, so the phase can never
    # mean "written but unverified"; recovery still re-proves it rather than trusting it.
    asset_bootstrap.verify_sot_integrity(sot, manifest)
    _write_journal(dist_premium, "sealed", token)
    if crash_hook is not None:
        crash_hook("sealed")
    shutil.rmtree(backup, ignore_errors=True)
    manifest_backup.unlink(missing_ok=True)
    _journal_path(dist_premium).unlink(missing_ok=True)


# The ONLY subtree of the premium_assets SoT this script is authorized to write.
OWNED_SUBTREE = "ffmpeg"


def install_target(dist_premium: Path) -> Path:
    """The single shipping source-of-truth for the LGPL DLLs (never repo models/)."""
    return asset_bootstrap.sot_ffmpeg_dir(dist_premium)


def require_sot(dist_premium: Path) -> Path:
    """Fail closed BEFORE the download: the SoT must exist AND be sealed.

    Checking only the directory left the SOT_UNSEALED refusal until after ~70 MB had
    already been fetched, verified and extracted."""
    sot, manifest = asset_bootstrap.sot_paths(dist_premium)
    if not sot.is_dir():
        raise SystemExit(
            f"premium_assets SoT not found: {sot} — run "
            "`python -m scripts.release.asset_bootstrap` first"
        )
    if not manifest.is_file():
        raise SystemExit(
            f"SOT_UNSEALED: {manifest} is missing, so the SoT cannot be trusted. "
            "Only the bootstrap mints a seal, and it needs the legacy dist_premium/models "
            "junction; restore the manifest from the machine that sealed this SoT, or "
            "re-create the SoT from the legacy layout."
        )
    return sot


def install_into_sot(build_dir: Path, dist_premium: Path, *, token: str = "1",
                     crash_hook: Callable[[str], None] | None = None) -> Path:
    """Install the verified LGPL set into the SoT and re-seal its integrity manifest.

    The SoT is verified BEFORE it is touched: this script owns ``models/ffmpeg`` and
    nothing else, so pre-existing drift anywhere else refuses the install instead of
    being laundered into a fresh seal. The whole flow runs under the shared asset lock,
    and the seal is re-written only after the subtree swap succeeded."""
    with asset_bootstrap.asset_lock(dist_premium):
        recover_ffmpeg_transaction(dist_premium)  # H7-3: finish/roll back BEFORE anything
        sot = require_sot(dist_premium)
        asset_bootstrap.verify_unowned_unchanged(dist_premium, owned=OWNED_SUBTREE,
                                                 _held=True)
        target = replace_owned_subtree(build_dir, dist_premium, token=token,
                                       crash_hook=crash_hook)
        _finish_transaction(dist_premium, token, crash_hook)
        print(f"SoT integrity manifest re-sealed for {sot}")
        return target


def stage_write_forbidden(*, staged: bool) -> bool:
    """External writes into the sealed premium_stage are forbidden (C2 lockdown).

    The sealed stage is composed only by scripts/release/stage_composer.py, which
    stages models/ffmpeg from the premium_assets source-of-truth. This installer
    may refresh that SoT (no ``--stage``) but must never write the stage directly.
    """
    return bool(staged)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install LGPL FFmpeg into the premium_assets source-of-truth")
    parser.add_argument(
        "--stage", action="store_true",
        help="DISABLED (C2): the sealed premium_stage is composed only by the stage composer",
    )
    parser.add_argument(
        "--dist", default=str(ROOT / "dist_premium"),
        help="dist_premium root that holds the premium_assets source-of-truth",
    )
    args = parser.parse_args()

    if stage_write_forbidden(staged=args.stage):
        print(
            "ERROR: --stage is disabled. The sealed premium_stage is composed only by "
            "scripts/release/stage_composer.py; run without --stage to refresh the "
            "models/ffmpeg source-of-truth.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    dist_premium = Path(args.dist)
    require_sot(dist_premium)  # refuse BEFORE downloading ~70 MB

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "ffmpeg-lgpl.zip"
            print(f"Downloading {ASSET_URL} ...")
            urllib.request.urlretrieve(ASSET_URL, zip_path)  # noqa: S310 — trusted host
            verify_download_sha256(zip_path, ASSET_SHA256)  # G5: fail-closed integrity pin
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_path)
            build_dir = next(tmp_path.glob("ffmpeg-*-win64-lgpl-shared-*"))
            _verify_lgpl(build_dir / "LICENSE.txt")
            print("Verified LICENSE is LGPL (not GPL).")

            install_into_sot(build_dir, dist_premium)
    except asset_bootstrap.BootstrapError as e:
        # A drifted SoT is a fail-closed refusal, not an operator-facing traceback.
        raise SystemExit(str(e)) from e

    print("Done. Re-run with the F5 engine to confirm torchcodec loads the LGPL DLLs.")


if __name__ == "__main__":
    main()
