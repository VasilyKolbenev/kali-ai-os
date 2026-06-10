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


async def test_stream_tts_synthesizes_long_sentences_individually() -> None:
    pipe = _pipeline()
    synth_calls: list[str] = []

    async def fake_stream(text, language=None):
        synth_calls.append(text)
        yield (np.array([0.1, 0.2, 0.1], dtype=np.float32), 24000)

    s1 = "Первое предложение получилось достаточно длинным."
    s2 = "Второе предложение получилось достаточно длинным."
    s3 = "Третье предложение получилось достаточно длинным."
    with patch(
        "kernel.voice.tts_router.generate_audio_stream", fake_stream
    ):
        await pipe._stream_tts(f"{s1} {s2} {s3}")

    # One synthesis call per sentence — NOT one big call for the whole text.
    assert synth_calls == [s1, s2, s3]
    # One tts_chunk published per sentence (first reaches the client fast).
    assert pipe._bus.publish.await_count == 3


async def test_stream_tts_merges_short_sentences_into_one_chunk() -> None:
    """Sub-min_chars sentences merge: F5's fixed per-call cost makes tiny
    chunks synthesize slower than they play, gapping the voice at periods."""
    pipe = _pipeline()
    synth_calls: list[str] = []

    async def fake_stream(text, language=None):
        synth_calls.append(text)
        yield (np.array([0.1], dtype=np.float32), 24000)

    with patch(
        "kernel.voice.tts_router.generate_audio_stream", fake_stream
    ):
        await pipe._stream_tts("Один. Два. Три.")

    assert synth_calls == ["Один. Два. Три."]
    assert pipe._bus.publish.await_count == 1


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

    s1 = "Первое предложение получилось достаточно длинным."
    s2 = "Второе предложение получилось достаточно длинным."
    s3 = "Третье предложение получилось достаточно длинным."
    with patch("kernel.voice.tts_router.generate_audio_stream", fake_stream):
        out = [
            pair
            async for pair in tts_router.generate_audio_by_sentence(f"{s1} {s2} {s3}")
        ]

    assert calls == [s1, s2, s3]
    assert len(out) == 3


async def test_streaming_deltas_emit_per_sentence_as_they_complete() -> None:
    """P1b wiring: LLM deltas fed through a SentenceBuffer emit a tts_chunk the
    moment each sentence closes — not after the whole reply arrives."""
    from kernel.voice.sentence_buffer import SentenceBuffer

    pipe = _pipeline()
    synth_calls: list[str] = []

    async def fake_stream(text, language=None):
        synth_calls.append(text)
        yield (np.array([0.1], dtype=np.float32), 24000)

    sb = SentenceBuffer()

    async def on_delta(delta: str) -> None:
        for sentence in sb.feed(delta):
            await pipe._emit_tts_for(sentence)

    with patch("kernel.voice.tts_router.generate_audio_stream", fake_stream):
        await on_delta("Привет, сэр, рад снова ")  # no boundary yet
        await on_delta("вас слышать сегодня. Чем я могу ")  # closes sentence 1
        await on_delta("помочь вам прямо сейчас, сэр? ")  # closes sentence 2
        tail = sb.flush()
        if tail:
            await pipe._emit_tts_for(tail)

    assert synth_calls == [
        "Привет, сэр, рад снова вас слышать сегодня.",
        "Чем я могу помочь вам прямо сейчас, сэр?",
    ]
    assert pipe._bus.publish.await_count == 2
