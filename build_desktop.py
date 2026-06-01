"""Build script — packages KALI into a standalone desktop application.

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
    run(f"{sys.executable} -m pip install pyinstaller")

    # Create PyInstaller spec
    spec = """
# KALI Kernel PyInstaller spec
import sys
sys.path.insert(0, '.')

a = Analysis(
    ['kernel/__main__.py'],
    pathex=['.'],
    datas=[
        ('config/kali.yaml', 'config'),
        ('agents', 'agents'),
        ('models', 'models'),
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
        'kernel.voice.tts_router',
        'kernel.voice.tts_engine_f5',
        'kernel.voice.tts_engine_elevenlabs',
        'kernel.voice.jarvis_sounds',
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
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='kali-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='kali-backend',
)
"""
    spec_path = ROOT / "kali-backend.spec"
    spec_path.write_text(spec)

    return run(f"{sys.executable} -m PyInstaller kali-backend.spec --clean --noconfirm")


def build_tauri() -> bool:
    """Build Tauri desktop app (requires Rust toolchain)."""
    print("\n=== Building Tauri Desktop App ===")

    # Check Rust
    result = subprocess.run("cargo --version", shell=True, capture_output=True)
    if result.returncode != 0:
        print("[SKIP] Rust toolchain not found. Install from https://rustup.rs")
        print("[SKIP] Tauri build skipped. Use start.bat for now.")
        return False

    # Setup dummy environment variables for Tauri updater signing if not present
    if "TAURI_PRIVATE_KEY" not in os.environ:
        print("[INFO] Setting dummy TAURI_PRIVATE_KEY for updater code signing...")
        os.environ["TAURI_PRIVATE_KEY"] = "dummy_private_key_base64"
        os.environ["TAURI_KEY_PASSWORD"] = "dummy_password"

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
    print("Kernel: dist/kali-backend.exe (if built)")
    print("UI:     ui/dist/ (static files)")
    print("\nTo run: start.bat or kali-backend.exe + serve ui/dist/")


if __name__ == "__main__":
    main()
