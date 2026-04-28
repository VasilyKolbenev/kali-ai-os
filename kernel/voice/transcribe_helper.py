"""Audio decode + resample helper for /voice/transcribe.

Ports the framing logic from `kernel.workers.tts_worker._handle_stt_transcribe`
so the FastAPI endpoint can call SpeechToText directly without spawning
a bridge subprocess.
"""

from __future__ import annotations

import base64
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.signal import resample_poly

if TYPE_CHECKING:
    from kernel.voice.stt import SpeechToText


_TARGET_SR = 16000

_stt_lock = threading.Lock()


def decode_and_resample(audio_b64: str, sample_rate: int) -> tuple[np.ndarray, int]:
    """Decode base64 i16 LE PCM, return float32 mono at 16 kHz.

    Args:
        audio_b64: Base64-encoded raw i16 little-endian PCM samples.
        sample_rate: Sample rate of the decoded samples.

    Returns:
        ``(audio_f32, target_sr)`` — float32 in [-1, 1] at 16 kHz mono.

    Raises:
        ValueError: If the decoded byte count is odd (i16 LE is
            inherently 2 bytes per sample).
    """
    raw = base64.b64decode(audio_b64)
    if len(raw) % 2 != 0:
        raise ValueError(
            f"audio_b64 length {len(raw)} not divisible by 2 (expected i16 LE)"
        )
    samples_i16 = np.frombuffer(raw, dtype="<i2")
    audio_f32 = samples_i16.astype(np.float32) / 32768.0

    if sample_rate != _TARGET_SR:
        from math import gcd

        g = gcd(sample_rate, _TARGET_SR)
        up = _TARGET_SR // g
        down = sample_rate // g
        audio_f32 = resample_poly(audio_f32, up, down).astype(np.float32)

    return audio_f32, _TARGET_SR


def get_or_create_stt(app_state: Any) -> "SpeechToText":
    """Return the cached SpeechToText, instantiating + loading on first use.

    Cached on `app_state.stt` so the Tauri build keeps a single model
    in memory across requests. Mirrors `tts_worker._ensure_stt()`
    (kernel/workers/tts_worker.py:107-124) so the bridge-process and
    the FastAPI endpoint converge on the same initialisation contract.

    `SpeechToText.__init__` only sets up state — `.load()` is what
    populates `_model` with the WhisperModel. Without `.load()` every
    call returns `STTResult(text="", language=None)` silently, which
    is exactly the failure mode the in-process port is meant to avoid.

    Thread-safe via a module lock — first request wins; subsequent
    requests reuse the cached instance.

    Raises:
        RuntimeError: If `SpeechToText.load()` fails to populate `_model`
            (e.g. missing model weights, GPU OOM).
    """
    existing = getattr(app_state, "stt", None)
    if existing is not None:
        return existing

    with _stt_lock:
        existing = getattr(app_state, "stt", None)
        if existing is not None:
            return existing
        from kernel.voice.stt import SpeechToText

        stt = SpeechToText(model_size="base", device="auto")
        stt.load()
        if not stt.is_loaded:
            raise RuntimeError(
                "Whisper failed to load — see kernel.voice.stt logs"
            )
        app_state.stt = stt
        return stt
