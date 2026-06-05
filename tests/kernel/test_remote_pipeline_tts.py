"""Sentence-incremental TTS streaming in the remote voice pipeline (P1a)."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.remote_pipeline import RemoteVoicePipeline


def _pipeline() -> RemoteVoicePipeline:
    bus = MagicMock()
    bus.subscribe = MagicMock()
    bus.publish = AsyncMock()
    return RemoteVoicePipeline(bus, VoiceConfig(), LLMConfig(), tools=[])


async def test_stream_tts_synthesizes_per_sentence() -> None:
    pipe = _pipeline()
    synth_calls: list[str] = []

    async def fake_stream(text, language=None):
        synth_calls.append(text)
        yield (np.array([0.1, 0.2, 0.1], dtype=np.float32), 24000)

    with patch(
        "kernel.voice.tts_router.generate_audio_stream", fake_stream
    ):
        await pipe._stream_tts("Один. Два. Три.")

    # One synthesis call per sentence — NOT one big call for the whole text.
    assert synth_calls == ["Один.", "Два.", "Три."]
    # One tts_chunk published per sentence (first reaches the client fast).
    assert pipe._bus.publish.await_count == 3


async def test_stream_tts_handles_unterminated_text() -> None:
    pipe = _pipeline()
    synth_calls: list[str] = []

    async def fake_stream(text, language=None):
        synth_calls.append(text)
        yield (np.array([0.1], dtype=np.float32), 24000)

    with patch(
        "kernel.voice.tts_router.generate_audio_stream", fake_stream
    ):
        await pipe._stream_tts("ответ без финальной точки")

    assert synth_calls == ["ответ без финальной точки"]  # flush() tail synthesized
    assert pipe._bus.publish.await_count == 1


async def test_generate_audio_by_sentence_helper_splits() -> None:
    from kernel.voice import tts_router

    calls: list[str] = []

    async def fake_stream(text, language=None):
        calls.append(text)
        yield (np.array([0.1], dtype=np.float32), 24000)

    with patch("kernel.voice.tts_router.generate_audio_stream", fake_stream):
        out = [pair async for pair in tts_router.generate_audio_by_sentence("А. Б. В.")]

    assert calls == ["А.", "Б.", "В."]
    assert len(out) == 3
