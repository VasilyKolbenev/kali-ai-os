"""Build KALI backend as a single .exe with PyInstaller.

Usage:
    cd C:/Users/User/Desktop/Jarvis
    uv run python scripts/build_backend.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENTRY = ROOT / "kernel" / "main.py"
DIST = ROOT / "dist"
NAME = "kali-backend"

# Data files to bundle
DATAS = [
    # Agent directories (manifests + code)
    (str(ROOT / "agents"), "agents"),
    # Config
    (str(ROOT / "config"), "config"),
    # RVC ONNX inference module
    (str(ROOT / "services" / "tts" / "rvc_onnx.py"), "services/tts"),
    # JARVIS voice clips
    (str(ROOT / "resources" / "sounds"), "resources/sounds"),
]

# Hidden imports that PyInstaller can't detect
HIDDEN = [
    "kernel.voice.tts_engine",
    "kernel.skill_executor",
    "kernel.skill_templates.tracker",
    "kernel.skill_templates.reminder",
    "kernel.skill_templates.monitor",
    "kernel.skill_templates.notifier",
    "kernel.skill_templates.logger",
    "kernel.sandbox.network_proxy",
    "kernel.sandbox.permission_enforcer",
    "kernel.sandbox.rate_limiter",
    "kernel.builder.intent_classifier",
    "kernel.builder.safety_gate",
    "kernel.builder.skill_generator",
    "kernel.builder.agent_generator",
    "kernel.builder.deployer",
    "kernel.builder.wizard",
    "kernel.catalog.package",
    "kernel.catalog.client",
    "kernel.catalog.installer",
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "yaml",
    "croniter",
    "faiss",
    "soundfile",
    "sounddevice",
    "onnxruntime",
]


def main() -> None:
    """Build the backend executable."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--console",  # Keep console for now (debug). Change to --noconsole for release.
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        # Icon
        "--icon", str(ROOT / "src-tauri" / "icons" / "icon.ico"),
    ]

    # Add data files
    for src, dst in DATAS:
        cmd.extend(["--add-data", f"{src};{dst}"])

    # Add hidden imports
    for imp in HIDDEN:
        cmd.extend(["--hidden-import", imp])

    # Entry point
    cmd.append(str(ENTRY))

    print(f"Building {NAME}.exe...")
    print(f"Command: {' '.join(cmd[:10])}...")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        exe = DIST / f"{NAME}.exe"
        size_mb = exe.stat().st_size / 1024 / 1024 if exe.exists() else 0
        print(f"\nSuccess! Built: {exe} ({size_mb:.1f} MB)")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
