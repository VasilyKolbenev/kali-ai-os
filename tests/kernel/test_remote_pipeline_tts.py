"""Sentence-incremental TTS streaming in the remote voice pipeline (P1a)."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import PipelineState
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

    # First sentence emits immediately (fast first audio); the remaining short
    # sentences merge into one chunk (no mid-speech gaps).
    assert synth_calls == ["Один.", "Два. Три."]
    assert pipe._bus.publish.await_count == 2


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


def test_no_debug_print_in_remote_pipeline() -> None:
    """The mobile-tethered path must not swallow failures into stdout prints —
    invisible errors leave the phone mute. All diagnostics go through logging."""
    import pathlib

    src = pathlib.Path(
        "kernel/voice/remote_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "print(" not in src
    assert "traceback.print_exc" not in src


async def test_stt_failure_logs_and_publishes_voice_error() -> None:
    """An STT exception must be logged via logger.exception AND surfaced to the
    client as a 'voice.error' event — not silently reset to IDLE."""
    pipe = _pipeline()
    pipe._app_state = MagicMock()
    pipe._audio_buffer = [b"\x00\x01" * 100]
    pipe._state = PipelineState.THINKING

    failing_stt = MagicMock()
    failing_stt.transcribe = MagicMock(side_effect=RuntimeError("ct2 blew up"))

    with patch(
        "kernel.voice.transcribe_helper.get_or_create_stt",
        return_value=failing_stt,
    ), patch("kernel.voice.remote_pipeline.logger") as mock_logger:
        await pipe._process_utterance()

    mock_logger.exception.assert_called_once()
    topics = [
        c.kwargs.get("event", c.args[0] if c.args else None)
        for c in pipe._bus.publish.await_args_list
    ]
    published_topics = [getattr(t, "topic", None) for t in topics]
    assert "voice.error" in published_topics
    assert pipe._state == PipelineState.IDLE
