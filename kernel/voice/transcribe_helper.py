"""Audio decode + resample helper for /voice/transcribe.

Ports the framing logic from `kernel.workers.tts_worker._handle_stt_transcribe`
so the FastAPI endpoint can call SpeechToText directly without spawning
a bridge subprocess.
"""

from __future__ import annotations

import base64

import numpy as np
from scipy.signal import resample_poly


_TARGET_SR = 16000


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
