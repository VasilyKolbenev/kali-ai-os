"""TTS provider router — F5-TTS (GPU) or ElevenLabs (cloud fallback).

Strategy:
- GPU users → F5-TTS Russian (our voice clone, offline)
- CPU/no-GPU → ElevenLabs cloud (temp; later: our own GPU inference server)
"""

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

PROVIDER_AUTO = "auto"
PROVIDER_F5 = "f5_russian"
PROVIDER_ELEVENLABS = "elevenlabs"
PROVIDERS = [PROVIDER_F5, PROVIDER_ELEVENLABS]

_active_provider: str | None = None
_active_module: Any = None


def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _has_elevenlabs_key() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())


def _resolve_provider(requested: str) -> str:
    """Resolve 'auto' → concrete provider based on hardware + keys."""
    if requested != PROVIDER_AUTO:
        return requested
    if _has_cuda():
        return PROVIDER_F5
    if _has_elevenlabs_key():
        return PROVIDER_ELEVENLABS
    # No GPU, no key — still default to ElevenLabs (will fail gracefully)
    logger.warning("No GPU and no ELEVENLABS_API_KEY — voice will not work")
    return PROVIDER_ELEVENLABS


def _load_module(provider: str) -> Any:
    if provider == PROVIDER_F5:
        from kernel.voice import tts_engine_f5 as mod
    elif provider == PROVIDER_ELEVENLABS:
        from kernel.voice import tts_engine_elevenlabs as mod
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")
    return mod


def get_provider() -> str:
    return _active_provider or PROVIDER_AUTO


def set_provider(provider: str) -> str:
    global _active_provider, _active_module
    resolved = _resolve_provider(provider)
    if resolved == _active_provider:
        return resolved
    _active_module = _load_module(resolved)
    _active_provider = resolved
    logger.info("TTS provider: %s (requested: %s)", resolved, provider)
    return resolved


def load_models() -> None:
    if _active_module is None:
        set_provider(os.environ.get("KALI_TTS_PROVIDER", PROVIDER_AUTO))
    assert _active_module is not None
    _active_module.load_models()


def is_loaded() -> bool:
    if _active_module is None:
        return False
    return bool(_active_module.is_loaded())


def generate_audio(text: str, language: str | None = None) -> tuple[np.ndarray, int]:
    """Generate audio via active provider. Falls back to the other one on failure."""
    if _active_module is None:
        set_provider(os.environ.get("KALI_TTS_PROVIDER", PROVIDER_AUTO))

    assert _active_module is not None
    try:
        return _active_module.generate_audio(text, language)
    except Exception as exc:
        logger.exception("TTS %s failed: %s — trying fallback", _active_provider, exc)
        fallback = PROVIDER_ELEVENLABS if _active_provider == PROVIDER_F5 else PROVIDER_F5
        set_provider(fallback)
        _active_module.load_models()  # type: ignore[union-attr]
        return _active_module.generate_audio(text, language)  # type: ignore[union-attr]


async def generate_audio_stream(text: str, language: str | None = None):
    """Generate audio stream via active provider. Falls back to the other one on failure."""
    if _active_module is None:
        set_provider(os.environ.get("KALI_TTS_PROVIDER", PROVIDER_AUTO))

    assert _active_module is not None
    try:
        if hasattr(_active_module, "generate_audio_stream"):
            async for chunk in _active_module.generate_audio_stream(text, language):
                yield chunk
        else:
            import asyncio
            audio, sr = await asyncio.to_thread(_active_module.generate_audio, text, language)
            yield audio, sr
    except Exception as exc:
        logger.exception("TTS %s stream failed: %s — trying fallback", _active_provider, exc)
        fallback = PROVIDER_ELEVENLABS if _active_provider == PROVIDER_F5 else PROVIDER_F5
        set_provider(fallback)
        _active_module.load_models()  # type: ignore[union-attr]
        if hasattr(_active_module, "generate_audio_stream"):
            async for chunk in _active_module.generate_audio_stream(text, language):  # type: ignore[union-attr]
                yield chunk
        else:
            import asyncio
            audio, sr = await asyncio.to_thread(_active_module.generate_audio, text, language)  # type: ignore[union-attr]
            yield audio, sr


def audio_to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    import io
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()
