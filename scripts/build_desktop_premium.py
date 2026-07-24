"""Build the Tauri desktop release and write its BUILD_RECEIPT (G2, OPUS-201).

The desktop artifact (``src-tauri/target/release/kali-desktop.exe``) carries a
build-time provenance receipt exactly like the backend: HEAD + clean-state are
captured BEFORE the build and re-checked after (the receipt is written only on a
successful build, refusing if HEAD moved), and the toolchain string comes from the
ACTUALLY-executed version commands (cargo/rustc/tauri), never a hardcoded label.

    python scripts/build_desktop_premium.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.release import receipts as rc  # noqa: E402

EXE = ROOT / "src-tauri" / "target" / "release" / "kali-desktop.exe"
_BUILD_CMD = ["npm", "--prefix", "ui", "exec", "--", "tauri", "build"]


def main() -> int:
    head_before, _clean = rc.capture_head_state(ROOT)
    print("Building Tauri desktop release ...")
    result = subprocess.run(_BUILD_CMD, cwd=str(ROOT), shell=(sys.platform == "win32"))
    if result.returncode != 0:
        print(f"Desktop build failed with exit code {result.returncode}", file=sys.stderr)
        return 1
    if not EXE.is_file():
        print(f"ERROR: expected {EXE} not found after a successful build", file=sys.stderr)
        return 1
    toolchain = rc.collect_toolchain([
        ("cargo", ["cargo", "--version"]),
        ("rustc", ["rustc", "--version"]),
        ("tauri", ["npm", "--prefix", "ui", "exec", "--", "tauri", "--version"]),
    ])
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    receipt_path = EXE.with_name(EXE.name + ".BUILD_RECEIPT.json")
    rc.finalize_build_receipt(EXE, receipt_path, repo=ROOT, version=version,
                              build_kind="tauri-release", toolchain=toolchain,
                              head_before=head_before)
    print(f"BUILD_RECEIPT written: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
