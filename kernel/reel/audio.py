"""Synthesize and normalize the agent voice clip for the reel."""
import numpy as np

from kernel.voice.tts_router import generate_audio


def synthesize_voice_clip(text: str) -> tuple[np.ndarray, int]:
    """Synthesize ``text`` via the active TTS provider, normalized.

    `generate_audio` only guarantees ``np.ndarray``; dtype/channel layout
    differs across F5 vs ElevenLabs. Normalize to float32 mono so the
    downstream waveform-envelope and audio-mux logic get a stable input.

    Returns:
        (float32 mono audio in [-1, 1], sample_rate).
    """
    audio, sr = generate_audio(text)
    arr = np.asarray(audio)
    if np.issubdtype(arr.dtype, np.integer):
        max_val = float(np.iinfo(arr.dtype).max) or 1.0
        arr = arr.astype(np.float32) / max_val
    else:
        arr = arr.astype(np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    return np.ascontiguousarray(arr, dtype=np.float32), int(sr)
