"""Build the Tauri desktop release and write its BUILD_RECEIPT (G2, OPUS-201).

The desktop artifact (``src-tauri/target/release/kali-desktop.exe``) carries a
build-time provenance receipt exactly like the backend: HEAD + clean-state are
captured BEFORE the build and re-checked after (the receipt is written only on a
successful build, refusing if HEAD moved), and the toolchain string comes from the
ACTUALLY-executed version commands (cargo/rustc/tauri), never a hardcoded label.

H1.3 — the build runs the exact command

    npm --prefix ui exec -- tauri build --no-bundle

with the npm LAUNCHER resolved on PATH (``npm.cmd`` on Windows) and
``shell=False``: passing an argv list with ``shell=True`` would re-join it through
cmd.exe, so every argument would be re-parsed by the shell.

    python scripts/build_desktop_premium.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.release import receipts as rc  # noqa: E402

EXE = ROOT / "src-tauri" / "target" / "release" / "kali-desktop.exe"
# The exact tauri build invocation (no bundling: the Premium installer is built by
# InnoSetup from the sealed stage, not by the tauri bundler).
_BUILD_ARGS = ["--prefix", "ui", "exec", "--", "tauri", "build", "--no-bundle"]
_VERSION_ARGS = ["--prefix", "ui", "exec", "--", "tauri", "--version"]

Runner = Callable[..., Any]
Which = Callable[[str], "str | None"]


class BuildError(RuntimeError):
    """The desktop build cannot run or did not produce its artifact (fail-closed)."""


def resolve_npm(which: Which | None = None) -> str:
    """Resolve the real npm launcher (``npm.cmd`` on Windows) — no shell bypass."""
    lookup = which or shutil.which
    for name in ("npm.cmd", "npm") if sys.platform == "win32" else ("npm",):
        found = lookup(name)
        if found:
            return found
    raise BuildError("NPM_MISSING: npm was not found on PATH")


def build_command(npm: str) -> list[str]:
    """``npm --prefix ui exec -- tauri build --no-bundle`` with a resolved launcher."""
    return [npm, *_BUILD_ARGS]


def main(*, runner: Runner = subprocess.run, which: Which | None = None) -> int:
    try:
        npm = resolve_npm(which)
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    # H6-3: refuse a dirty worktree BEFORE the build — a dirty build can never earn a
    # receipt, so running it only burns time and leaves an unusable artifact.
    head_before, clean_before = rc.capture_head_state(ROOT)
    if not clean_before:
        print("ERROR: DIRTY_AT_START: the worktree is dirty — build from a clean "
              "dedicated worktree", file=sys.stderr)
        return 1
    print("Building Tauri desktop release ...")
    result = runner(build_command(npm), cwd=str(ROOT))
    if result.returncode != 0:
        print(f"Desktop build failed with exit code {result.returncode}", file=sys.stderr)
        return 1
    if not EXE.is_file():
        print(f"ERROR: expected {EXE} not found after a successful build", file=sys.stderr)
        return 1
    try:
        toolchain = rc.collect_toolchain([
            ("cargo", ["cargo", "--version"]),
            ("rustc", ["rustc", "--version"]),
            ("tauri", [npm, *_VERSION_ARGS]),
        ])
    except rc.ReceiptError as e:
        print(f"ERROR: {e}", file=sys.stderr)  # fail-closed: no receipt without a toolchain
        return 1
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    receipt_path = EXE.with_name(EXE.name + ".BUILD_RECEIPT.json")
    try:
        rc.finalize_build_receipt(EXE, receipt_path, repo=ROOT, version=version,
                                  build_kind="tauri-release", toolchain=toolchain,
                                  head_before=head_before, clean_before=clean_before)
    except rc.ReceiptError as e:
        # F3: a refused receipt is an operator-facing failure, not a traceback.
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"BUILD_RECEIPT written: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
