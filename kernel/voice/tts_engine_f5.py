"""F5-TTS engine — voice cloning from JARVIS reference clips.

Setup:
- Russian fine-tune: Misha24-10/F5-TTS_RUSSIAN (v4_winter checkpoint)
- Reference: jarvis_ref_v2.wav (9.62s, 4 clips from Sound Pack)
- Tuned params: speed=1.0, cfg_strength=3.5, nfe_step=64, remove_silence=False
  (winner of A/B test "04_v2ref_aggressive" on 2026-04-22)
- Requires: CUDA GPU + FFmpeg shared DLLs (models/ffmpeg/)
"""

import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _register_ffmpeg_dll_path() -> None:
    """Add bundled FFmpeg DLL directory to search path (for torchcodec)."""
    if hasattr(sys, "_MEIPASS"):
        exe_dir = Path(sys.executable).parent
        candidates = [exe_dir / "models" / "ffmpeg"]
    else:
        candidates = [Path(__file__).parent.parent.parent / "models" / "ffmpeg"]

    for cand in candidates:
        if cand.exists() and any(cand.glob("avcodec-*.dll")):
            try:
                os.add_dll_directory(str(cand))
                os.environ["PATH"] = f"{cand};{os.environ.get('PATH', '')}"
                logger.info("FFmpeg DLLs registered from %s", cand)
                return
            except Exception as exc:
                logger.warning("Failed to register FFmpeg DLLs: %s", exc)
    logger.warning("FFmpeg DLLs not found — F5-TTS may fail to load audio")


_register_ffmpeg_dll_path()


def _models_dir() -> Path:
    """Resolve the directory that holds F5 weights + reference WAVs.

    PyInstaller onedir layout after InnoSetup install is:
        {app}/kali-backend/kali-backend.exe   (sys.executable)
        {app}/kali-backend/_internal/
        {app}/models/                          ← models sit ONE LEVEL UP

    We search in priority order and return the first that exists.
    """
    if hasattr(sys, "_MEIPASS"):
        exe_dir = Path(sys.executable).parent
        appdata = Path(os.environ.get("APPDATA", "")) / "KALI"
        candidates = [
            exe_dir / "models",           # legacy: models next to exe
            exe_dir.parent / "models",    # InnoSetup layout: one level up
            appdata / "models",           # user override in %APPDATA%
        ]
        for c in candidates:
            if c.exists():
                logger.info("F5 models dir resolved: %s", c)
                return c
        logger.warning(
            "F5 models dir not found in any candidate: %s",
            [str(c) for c in candidates],
        )
        return exe_dir.parent / "models"  # best-guess default for the frozen layout
    return Path(__file__).parent.parent.parent / "models"


MODELS_DIR = _models_dir()
REFERENCE_AUDIO = MODELS_DIR / "jarvis_ref_v2.wav"
REFERENCE_TEXT = (
    "Вы создали новый элемент. Запрос выполнен, сэр. "
    "Загружаю, сэр. Импортирую установки, начинаю калибровку виртуальной среды."
)

# Tuned inference parameters — A/B winner "04_v2ref_aggressive" (2026-04-22)
SPEED = 1.0           # natural pacing
CFG_STRENGTH = 2.0    # balanced: voice similarity vs speed
NFE_STEP = 32         # default quality (was 64 — high but slow, 32 is 2x faster)
REMOVE_SILENCE = False  # preserve natural butler pauses

# Global state
_f5_instance: Any = None
_loaded = False


def _checkpoint_paths() -> tuple[Path, Path]:
    """Locate Russian fine-tune checkpoint + vocab.

    Priority: local models dir, then HuggingFace cache.
    """
    local_ckpt = MODELS_DIR / "f5_russian_v4_winter.safetensors"
    local_vocab = MODELS_DIR / "f5_russian_vocab.txt"
    if local_ckpt.exists() and local_vocab.exists():
        return local_ckpt, local_vocab

    # Fallback: HuggingFace hub cache
    from huggingface_hub import hf_hub_download
    ckpt = hf_hub_download(
        repo_id="Misha24-10/F5-TTS_RUSSIAN",
        filename="F5TTS_v1_Base_v4_winter/model_212000.safetensors",
    )
    vocab = hf_hub_download(
        repo_id="Misha24-10/F5-TTS_RUSSIAN",
        filename="F5TTS_v1_Base/vocab.txt",
    )
    return Path(ckpt), Path(vocab)


def _get_f5() -> Any:
    """Load F5-TTS Russian fine-tune (lazy, cached)."""
    global _f5_instance
    if _f5_instance is not None:
        return _f5_instance

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        logger.warning("F5-TTS on CPU is very slow — GPU recommended")

    ckpt, vocab = _checkpoint_paths()
    logger.info("Loading F5-TTS Russian (%s)...", device)

    from f5_tts.api import F5TTS
    _f5_instance = F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=str(ckpt),
        vocab_file=str(vocab),
        device=device,
    )
    logger.info("F5-TTS ready")
    return _f5_instance


def load_models() -> None:
    """Load F5-TTS model. Safe to call multiple times."""
    global _loaded
    if _loaded:
        return
    if not REFERENCE_AUDIO.exists():
        raise FileNotFoundError(f"Reference audio not found: {REFERENCE_AUDIO}")
    _get_f5()
    _loaded = True
    logger.info("F5-TTS engine ready (reference: %s)", REFERENCE_AUDIO.name)


def is_loaded() -> bool:
    return _loaded


def _fix_text(text: str) -> str:
    """Strip markdown bold + apply Russian preprocessing (stress, punctuation, numbers)."""
    from kernel.voice.text_preprocessor import preprocess
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return preprocess(text.strip())


_reference_text_processed: str | None = None


def _get_processed_reference_text() -> str:
    """Apply the same preprocessing to the reference text so stress marks match gen_text."""
    global _reference_text_processed
    if _reference_text_processed is None:
        from kernel.voice.text_preprocessor import preprocess
        _reference_text_processed = preprocess(REFERENCE_TEXT)
        logger.debug("Processed reference text: %s", _reference_text_processed)
    return _reference_text_processed


def _split_sentences(text: str) -> list[str]:
    """Split into sentences for chunked generation."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    result: list[str] = []
    buf = ""
    for p in parts:
        if len(buf) + len(p) < 300:
            buf = f"{buf} {p}".strip() if buf else p
        else:
            if buf:
                result.append(buf)
            buf = p
    if buf:
        result.append(buf)
    return result if result else [text]


def generate_audio(text: str, language: str | None = None) -> tuple[np.ndarray, int]:
    """Generate JARVIS voice via F5-TTS Russian fine-tune."""
    del language  # F5 auto-detects
    f5 = _get_f5()
    text = _fix_text(text)

    sentences = _split_sentences(text)
    all_audio: list[np.ndarray] = []

    t0 = time.perf_counter()
    for sentence in sentences:
        try:
            wav, sr, _ = f5.infer(
                ref_file=str(REFERENCE_AUDIO),
                ref_text=_get_processed_reference_text(),
                gen_text=sentence,
                remove_silence=REMOVE_SILENCE,
                speed=SPEED,
                cfg_strength=CFG_STRENGTH,
                nfe_step=NFE_STEP,
            )
            all_audio.append(np.asarray(wav, dtype=np.float32))
        except Exception as exc:
            logger.warning("F5 failed on %r: %s", sentence[:40], exc)
            continue

    if not all_audio:
        return np.zeros(1600, dtype=np.float32), 24000

    audio = np.concatenate(all_audio)
    elapsed = time.perf_counter() - t0
    logger.info("F5-TTS: %d chars → %.1fs audio in %.2fs", len(text), len(audio) / 24000, elapsed)

    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = (audio * 0.7 / peak).astype(np.float32)

    return audio, 24000


async def generate_audio_stream(text: str, language: str | None = None):
    """Generate JARVIS voice via F5-TTS and yield chunks per sentence."""
    import asyncio
    del language  # F5 auto-detects
    f5 = _get_f5()
    text = _fix_text(text)

    sentences = _split_sentences(text)

    for sentence in sentences:
        t0 = time.perf_counter()
        try:
            wav, sr, _ = await asyncio.to_thread(
                f5.infer,
                ref_file=str(REFERENCE_AUDIO),
                ref_text=_get_processed_reference_text(),
                gen_text=sentence,
                remove_silence=REMOVE_SILENCE,
                speed=SPEED,
                cfg_strength=CFG_STRENGTH,
                nfe_step=NFE_STEP,
            )
            audio = np.asarray(wav, dtype=np.float32)
            elapsed = time.perf_counter() - t0
            logger.info("F5-TTS stream: %d chars → %.1fs audio in %.2fs", len(sentence), len(audio) / 24000, elapsed)
            
            peak = float(np.max(np.abs(audio)))
            if peak > 0:
                audio = (audio * 0.7 / peak).astype(np.float32)

            yield audio, 24000
        except Exception as exc:
            logger.warning("F5 failed on %r: %s", sentence[:40], exc)
            continue


def audio_to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    import io
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()
