"""Build Premium backend — F5-TTS + CUDA torch for local GPU voice synthesis.

Target: ~4GB installer (includes torch+cu128, F5 model, FFmpeg DLLs).
For users with NVIDIA GPU (RTX 20+ series) who want fully offline JARVIS voice.

Distribution: Google Drive / Yandex.Disk link (too big for Telegram).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENTRY = ROOT / "kernel" / "entry.py"
DIST = ROOT / "dist_premium"
NAME = "kali-backend"

DATAS = [
    (str(ROOT / "agents"), "agents"),
    (str(ROOT / "config"), "config"),
    (str(ROOT / "resources" / "sounds"), "resources/sounds"),
]

HIDDEN = [
    "kernel.runtime_paths",
    "kernel.model_downloader",
    "kernel.jarvis_persona",
    "kernel.voice.tts_router",
    "kernel.voice.tts_engine_f5",
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
    # F5-TTS + torch CUDA stack
    "f5_tts",
    "f5_tts.api",
    "f5_tts.infer",
    "f5_tts.model",
    "vocos",
    "torch",
    "torchaudio",
    "torchaudio.compliance",
    "torchaudio.compliance.kaldi",
    "torchaudio.transforms",
    "torchcodec",
    "transformers",
    "huggingface_hub",
    "faster_whisper",
    "elevenlabs",
    "elevenlabs.client",
]


def main() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onedir",  # NSIS-friendly for 3+ GB backend
        "--console",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "pyinstaller_premium"),
        "--specpath", str(ROOT / "build"),
        "--noconfirm",
        "--icon", str(ROOT / "src-tauri" / "icons" / "icon.ico"),
    ]

    for src, dst in DATAS:
        cmd.extend(["--add-data", f"{src};{dst}"])
    for imp in HIDDEN:
        cmd.extend(["--hidden-import", imp])

    cmd.append(str(ENTRY))

    print(f"Building Premium {NAME} (F5 + CUDA torch)...")
    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        out_dir = DIST / NAME
        if out_dir.exists():
            total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
            print(f"\nSuccess! Built Premium backend at {out_dir}")
            print(f"Size: {total / 1024 / 1024 / 1024:.2f} GB uncompressed")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
