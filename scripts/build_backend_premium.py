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
    "kernel.voice.text_preprocessor",
    "kernel.voice.jarvis_sounds",
    "kernel.voice.pipeline",
    "kernel.voice.vad",
    "kernel.voice.stt",
    "kernel.voice.wake_word",
    "kernel.voice.recorder",
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
    "ruaccent",
    "onnxruntime",
]

# Packages whose runtime data files (e.g. bundled .onnx models, configs)
# must be collected into the PyInstaller bundle. Without these, packages
# look at <pkg>/resources/ at runtime and fail with NO_SUCHFILE.
#
# - openwakeword: ships 9 .onnx models (incl hey_jarvis, alexa, melspectrogram)
#   under openwakeword/resources/models/.
# - f5_tts / vocos: bundled configs + small data referenced by F5TTS().
# - ruaccent: Russian accent dictionary for TTS preprocessing.
# - faster_whisper: model assets used at first-run download path.
COLLECT_DATA = [
    "openwakeword",
    "f5_tts",
    "vocos",
    "ruaccent",
    "faster_whisper",
]

# Packages that need EVERYTHING — Python source + data + binaries. Required
# when the package uses lazy imports (`_LazyModule`) that PyInstaller's
# static analyzer can't detect at build time.
#
# - transformers: f5_tts.infer.utils_infer does `from transformers import
#   pipeline` at module level; transformers/__init__.py lazy-loads submodules
#   via _LazyModule which PyInstaller misses. Without --collect-all the v2
#   build crashed with ModuleNotFoundError on every F5 load attempt
#   (root cause caught 2026-05-18 during max-confidence debug session).
# - torch: heavy stack with submodules pulled lazily by transformers/f5_tts.
#   Belt-and-suspenders even though `torch` is in HIDDEN.
COLLECT_ALL = [
    "transformers",
    "torch",
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
    for pkg in COLLECT_DATA:
        cmd.extend(["--collect-data", pkg])
    for pkg in COLLECT_ALL:
        cmd.extend(["--collect-all", pkg])

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
