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

Usage:
    python scripts/fetch_lgpl_ffmpeg.py            # install into models/ffmpeg/
    python scripts/fetch_lgpl_ffmpeg.py --stage    # also refresh dist_premium/premium_stage
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# G5: pin the release to an immutable, dated autobuild tag (NOT the mutable "latest"
# tag) and verify the download against a pinned SHA256. The tag + SHA256 are owner-
# pinned values; an empty ASSET_SHA256 fails closed (refuses to install unverified
# bytes). Update both together when bumping the FFmpeg build.
FFMPEG_TAG = "autobuild-2025-01-01-12-30"  # owner-pinned immutable tag (placeholder)
ASSET_URL = (
    f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{FFMPEG_TAG}/"
    "ffmpeg-n8.1-win64-lgpl-shared-8.1.zip"
)
ASSET_SHA256 = ""  # owner-pinned SHA256 of the exact asset; empty => fail closed


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


def _install(build_dir: Path, target: Path) -> None:
    """Copy the 7 LGPL DLLs + LICENSE.txt into ``target`` (models/ffmpeg)."""
    target.mkdir(parents=True, exist_ok=True)
    bin_dir = build_dir / "bin"
    found = {p.name for p in bin_dir.glob("*.dll")}
    missing = EXPECTED_DLLS - found
    if missing:
        raise SystemExit(f"LGPL build missing expected DLLs: {sorted(missing)}")
    for name in EXPECTED_DLLS:
        shutil.copy2(bin_dir / name, target / name)
    shutil.copy2(build_dir / "LICENSE.txt", target / "LICENSE.txt")
    print(f"Installed {len(EXPECTED_DLLS)} LGPL DLLs + LICENSE.txt -> {target}")


def stage_write_forbidden(*, staged: bool) -> bool:
    """External writes into the sealed premium_stage are forbidden (C2 lockdown).

    The sealed stage is composed only by scripts/release/stage_composer.py, which
    stages models/ffmpeg from the premium_assets source-of-truth. This installer
    may refresh that SoT (no ``--stage``) but must never write the stage directly.
    """
    return bool(staged)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install LGPL FFmpeg into models/ffmpeg/")
    parser.add_argument(
        "--stage", action="store_true",
        help="DISABLED (C2): the sealed premium_stage is composed only by the stage composer",
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

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "ffmpeg-lgpl.zip"
        print(f"Downloading {ASSET_URL} ...")
        urllib.request.urlretrieve(ASSET_URL, zip_path)  # noqa: S310 — trusted release host
        verify_download_sha256(zip_path, ASSET_SHA256)  # G5: fail-closed integrity pin
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)
        build_dir = next(tmp_path.glob("ffmpeg-*-win64-lgpl-shared-*"))
        _verify_lgpl(build_dir / "LICENSE.txt")
        print("Verified LICENSE is LGPL (not GPL).")

        _install(build_dir, ROOT / "models" / "ffmpeg")

    print("Done. Re-run with the F5 engine to confirm torchcodec loads the LGPL DLLs.")


if __name__ == "__main__":
    main()
