"""Build script — packages Jarvis into a standalone desktop application.

Steps:
1. Build UI (Vite production bundle)
2. Package Python kernel into .exe (PyInstaller)
3. Build Tauri desktop app (if Rust toolchain available)

Usage:
    python build_desktop.py          # full build
    python build_desktop.py --ui     # UI only
    python build_desktop.py --kernel # kernel .exe only
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def run(cmd: str, cwd: Path | None = None) -> bool:
    """Run a shell command and return success status."""
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd or ROOT)
    return result.returncode == 0


def build_ui() -> bool:
    """Build React UI with Vite."""
    print("\n=== Building UI ===")
    return run("pnpm build", cwd=ROOT / "ui")


def build_kernel() -> bool:
    """Package Python kernel into standalone .exe with PyInstaller."""
    print("\n=== Building Kernel .exe ===")

    # Install PyInstaller if needed
    run("uv pip install pyinstaller")

    # Create PyInstaller spec
    spec = """
# Jarvis Kernel PyInstaller spec
import sys
sys.path.insert(0, '.')

a = Analysis(
    ['kernel/__main__.py'],
    pathex=['.'],
    datas=[
        ('config/jarvis.yaml', 'config'),
        ('agents', 'agents'),
    ],
    hiddenimports=[
        'kernel.main',
        'kernel.event_bus',
        'kernel.config_manager',
        'kernel.database',
        'kernel.plugin_registry',
        'kernel.scheduler',
        'kernel.models',
        'kernel.memory',
        'kernel.notifications',
        'kernel.briefing',
        'kernel.budget',
        'kernel.focus',
        'kernel.routines',
        'kernel.agent_builder',
        'kernel.llm_router',
        'kernel.voice',
        'kernel.voice.pipeline',
        'kernel.voice.recorder',
        'kernel.voice.vad',
        'kernel.voice.wake_word',
        'kernel.voice.stt',
        'kernel.voice.tts',
        'kernel.agent_runtime',
        'kernel.agent_runtime.runtime',
        'kernel.agent_runtime.dispatcher',
        'kernel.agent_runtime.protocols.native',
        'kernel.agent_runtime.protocols.http_client',
        'kernel.integrations',
        'kernel.integrations.google_auth',
        'uvicorn',
        'fastapi',
        'pydantic',
        'yaml',
        'aiosqlite',
        'dotenv',
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name='jarvis-kernel',
    console=True,
    icon=None,
)
"""
    spec_path = ROOT / "jarvis-kernel.spec"
    spec_path.write_text(spec)

    return run("uv run pyinstaller jarvis-kernel.spec --clean --noconfirm")


def build_tauri() -> bool:
    """Build Tauri desktop app (requires Rust toolchain)."""
    print("\n=== Building Tauri Desktop App ===")

    # Check Rust
    result = subprocess.run("cargo --version", shell=True, capture_output=True)
    if result.returncode != 0:
        print("[SKIP] Rust toolchain not found. Install from https://rustup.rs")
        print("[SKIP] Tauri build skipped. Use start.bat for now.")
        return False

    return run("cargo tauri build", cwd=ROOT / "src-tauri")


def main() -> None:
    args = sys.argv[1:]

    if not args or "--ui" in args:
        if not build_ui():
            print("[ERROR] UI build failed")
            sys.exit(1)

    if not args or "--kernel" in args:
        if not build_kernel():
            print("[ERROR] Kernel build failed")
            sys.exit(1)

    if not args:
        build_tauri()  # Optional, doesn't fail the build

    print("\n=== Build Complete ===")
    print("Kernel: dist/jarvis-kernel.exe (if built)")
    print("UI:     ui/dist/ (static files)")
    print("\nTo run: start.bat or jarvis-kernel.exe + serve ui/dist/")


if __name__ == "__main__":
    main()
