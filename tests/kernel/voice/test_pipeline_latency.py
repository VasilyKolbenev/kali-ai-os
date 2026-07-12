"""Latency-surgery invariants of the desktop voice pipeline (Sprint 1)."""
from kernel.event_bus import EventBus
from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import VoicePipeline


def _mk() -> VoicePipeline:
    return VoicePipeline(EventBus(), VoiceConfig(), LLMConfig(), tools=[])


def test_default_silence_window_is_900ms(monkeypatch) -> None:
    monkeypatch.delenv("KALI_SILENCE_MS", raising=False)
    p = _mk()
    assert p._max_silence_chunks == 900 // 32  # 28 chunks


def test_silence_window_env_override(monkeypatch) -> None:
    monkeypatch.setenv("KALI_SILENCE_MS", "2500")
    p = _mk()
    assert p._max_silence_chunks == 2500 // 32
