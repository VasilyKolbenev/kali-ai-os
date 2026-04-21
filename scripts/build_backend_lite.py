"""Build Lite backend — no F5/CUDA torch. Uses ElevenLabs cloud TTS only.

Target: ~300-500 MB installer, fits in Telegram (2 GB limit).
For users without GPU or who don't want local F5-TTS.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENTRY = ROOT / "kernel" / "entry.py"
DIST = ROOT / "dist_lite"
NAME = "kali-backend"

DATAS = [
    (str(ROOT / "agents"), "agents"),
    (str(ROOT / "config"), "config"),
    (str(ROOT / "resources" / "sounds"), "resources/sounds"),
]

# Hidden imports — no torch/F5/torchcodec (huge GPU deps)
HIDDEN = [
    "kernel.runtime_paths",
    "kernel.model_downloader",
    "kernel.jarvis_persona",
    "kernel.voice.tts_router",
    "kernel.voice.tts_engine_elevenlabs",
    "kernel.skill_executor",
    "kernel.skill_templates.tracker",
    "kernel.skill_templates.reminder",
    "kernel.skill_templates.monitor",
    "kernel.skill_templates.notifier",
    "kernel.skill_templates.logger",
    "kernel.sandbox.network_proxy",
    "kernel.sandbox.permission_enforcer",
    "kernel.sandbox.rate_limiter",
    "kernel.sandbox.backend",
    "kernel.sandbox.audit",
    "kernel.sandbox.http_client",
    "kernel.skills",
    "kernel.skills.loader",
    "kernel.skills.validator",
    "kernel.skills.registry",
    "kernel.skills.converter",
    "kernel.skills.catalog",
    "kernel.skills.installer",
    "kernel.skills.publisher",
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
    "soundfile",
    "sounddevice",
    "openwakeword.model",
    "requests",
    "elevenlabs",
    "elevenlabs.client",
]

# Exclude heavy GPU/local-TTS modules (not used in Lite)
EXCLUDES = [
    "torch",
    "torchvision",
    "torchaudio",
    "torchcodec",
    "f5_tts",
    "vocos",
    "transformers",
    "huggingface_hub",
    "onnxruntime",
    "onnxruntime_directml",
    "faiss",
    "faster_whisper",  # STT also heavy — users can enable later
    "scipy",
    "numba",
    "llvmlite",
    "matplotlib",
    "tensorflow",
    "jax",
    "wandb",
    "pandas",
    "tiktoken",
    "sympy",
    "networkx",
]


def main() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onedir",  # NSIS-friendly
        "--console",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "pyinstaller_lite"),
        "--specpath", str(ROOT / "build"),
        "--noconfirm",
        "--icon", str(ROOT / "src-tauri" / "icons" / "icon.ico"),
    ]

    for src, dst in DATAS:
        cmd.extend(["--add-data", f"{src};{dst}"])
    for imp in HIDDEN:
        cmd.extend(["--hidden-import", imp])
    for mod in EXCLUDES:
        cmd.extend(["--exclude-module", mod])

    cmd.append(str(ENTRY))

    print(f"Building Lite {NAME} (no GPU/F5)...")
    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        out_dir = DIST / NAME
        if out_dir.exists():
            total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
            print(f"\nSuccess! Built Lite backend at {out_dir}")
            print(f"Size: {total / 1024 / 1024:.1f} MB uncompressed")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
