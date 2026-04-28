"""Helper that decodes base64 i16 LE PCM and resamples to 16 kHz.

Mirrors `kernel.workers.tts_worker._handle_stt_transcribe` lines
143-199, extracted so the new HTTP endpoint can call it without
crossing a subprocess boundary.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

from kernel.voice.transcribe_helper import decode_and_resample


def _make_audio_b64(samples_i16: np.ndarray) -> str:
    return base64.b64encode(samples_i16.astype("<i2").tobytes()).decode("ascii")


def test_decode_passthrough_at_16khz() -> None:
    samples = np.array([0, 1000, -1000, 0, 32767, -32768], dtype="<i2")
    out, sr = decode_and_resample(_make_audio_b64(samples), sample_rate=16000)
    assert sr == 16000
    assert out.dtype == np.float32
    assert len(out) == len(samples)
    np.testing.assert_allclose(out[1], 1000 / 32768.0, atol=1e-4)


def test_decode_resamples_48khz_to_16khz() -> None:
    samples = np.zeros(4800, dtype="<i2")  # 100ms at 48 kHz
    samples[::3] = 1000  # tone-ish
    out, sr = decode_and_resample(_make_audio_b64(samples), sample_rate=48000)
    assert sr == 16000
    # 4800 in @ 48k → 1600 out @ 16k (3:1 ratio)
    assert abs(len(out) - 1600) <= 5  # resample_poly polyphase tolerance
    assert out.dtype == np.float32


def test_decode_rejects_odd_byte_length() -> None:
    bad = base64.b64encode(b"\x01\x02\x03").decode("ascii")  # 3 bytes — not divisible by 2
    with pytest.raises(ValueError, match="not divisible by 2"):
        decode_and_resample(bad, sample_rate=16000)


# ── get_or_create_stt — cold-init path ────────────────────────────────


class _FakeAppState:
    """Minimal stand-in for FastAPI app.state — just an attribute bag."""

    pass


def test_get_or_create_stt_returns_cached_instance() -> None:
    """When `app_state.stt` is already set, helper returns it without
    instantiating SpeechToText (covers the test-fixture / hot-request path)."""
    from kernel.voice.transcribe_helper import get_or_create_stt

    state = _FakeAppState()
    sentinel = object()  # any non-None value short-circuits the lazy-init
    state.stt = sentinel  # type: ignore[attr-defined]
    assert get_or_create_stt(state) is sentinel


def test_get_or_create_stt_raises_when_load_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """If SpeechToText().load() runs but `is_loaded` stays False, the helper
    surfaces a RuntimeError so the endpoint maps to 500 (instead of silently
    returning empty transcripts forever)."""
    from kernel.voice import transcribe_helper

    class _FakeStt:
        def __init__(self, model_size: str = "base", device: str = "auto") -> None:
            self.model_size = model_size
            self.device = device
            self.is_loaded = False

        def load(self) -> None:
            # Simulate load failure: model weights missing, GPU OOM, etc.
            return None

    monkeypatch.setattr(
        "kernel.voice.stt.SpeechToText",
        _FakeStt,
    )

    state = _FakeAppState()
    with pytest.raises(RuntimeError, match="Whisper failed to load"):
        transcribe_helper.get_or_create_stt(state)
    # Confirm cache was NOT populated on failure.
    assert getattr(state, "stt", None) is None
