"""Desktop pipeline LLM→TTS streaming (Sprint 1 Task 7, port of remote P1b).

All GPU/audio boundaries are mocked: tts_router.generate_audio_stream,
_play_audio, LLMRouter.route_streaming, recorder.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

import kernel.voice.pipeline as pipeline_mod
from kernel.event_bus import EventBus
from kernel.llm_router import LLMResponse
from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import VoicePipeline
from kernel.voice.stt import STTResult


def _mk() -> VoicePipeline:
    p = VoicePipeline(EventBus(), VoiceConfig(), LLMConfig(), tools=[])
    app_state = MagicMock()
    app_state.long_term_memory = None
    app_state.builder_flow = None
    p._app_state = app_state
    return p


def _stt(text: str = "привет") -> STTResult:
    return STTResult(text=text, language="ru", confidence=1.0, duration_ms=10)


@pytest.fixture
def fake_tts(monkeypatch):
    """generate_audio_stream → instant fake audio; records synthesized texts."""
    synthesized: list[str] = []

    async def fake_stream(text: str, language=None):
        synthesized.append(text)
        yield np.ones(240, dtype=np.float32), 24000

    monkeypatch.setattr(pipeline_mod.tts_router, "generate_audio_stream", fake_stream)
    return synthesized


@pytest.fixture
def played(monkeypatch):
    """_play_audio → recorder of playback calls (no sounddevice)."""
    calls: list[int] = []

    def fake_play(audio, sr) -> None:
        calls.append(len(audio))

    monkeypatch.setattr(pipeline_mod, "_play_audio", fake_play)
    return calls


async def test_first_sentence_plays_before_stream_completes(fake_tts, played) -> None:
    p = _mk()
    gate = asyncio.Event()

    async def fake_route_streaming(request, on_delta):
        await on_delta("Первое предложение готово. ")
        # Wait until the test observes playback of sentence 1, proving
        # audio flows while the LLM is still "generating".
        await asyncio.wait_for(gate.wait(), timeout=5)
        await on_delta("Второе предложение.")
        return LLMResponse(text="Первое предложение готово. Второе предложение.",
                           tool_calls=None, provider_used="openai", latency_ms=0)

    p._llm.route_streaming = fake_route_streaming  # type: ignore[method-assign]

    async def unblock_when_played() -> None:
        while not played:
            await asyncio.sleep(0.005)
        gate.set()

    unblocker = asyncio.create_task(unblock_when_played())
    await p._handle_transcription(_stt())
    await unblocker

    assert played, "no audio reached playback"
    assert any("Первое предложение" in s for s in fake_tts)


async def test_tool_call_turn_speaks_result_once_via_guard(fake_tts, played, monkeypatch) -> None:
    p = _mk()

    async def fake_route_streaming(request, on_delta):
        # Model chose a tool: empty stream, tool_calls in the recovered response.
        return LLMResponse(text="", tool_calls=[MagicMock(name="tool")],
                           provider_used="openai", latency_ms=0)

    p._llm.route_streaming = fake_route_streaming  # type: ignore[method-assign]

    async def fake_dispatch(state, llm, calls, ctx, text):
        return ("Готово, сэр.", None, "agent")

    import kernel.tool_dispatch
    monkeypatch.setattr(kernel.tool_dispatch, "execute_tool_calls", fake_dispatch)

    guard_calls: list[str] = []

    async def fake_guard(text: str) -> None:
        guard_calls.append(text)

    p._play_tts_with_guard = fake_guard  # type: ignore[method-assign]

    await p._handle_transcription(_stt("сделай задачу"))

    assert guard_calls == ["Готово, сэр."]
    assert not fake_tts, "tool turn must not stream-synthesize the empty reply"


async def test_plain_turn_does_not_double_speak(fake_tts, played) -> None:
    p = _mk()

    async def fake_route_streaming(request, on_delta):
        await on_delta("Ответ целиком одним куском.")
        return LLMResponse(text="Ответ целиком одним куском.", tool_calls=None,
                           provider_used="openai", latency_ms=0)

    p._llm.route_streaming = fake_route_streaming  # type: ignore[method-assign]

    guard_calls: list[str] = []

    async def fake_guard(text: str) -> None:
        guard_calls.append(text)

    p._play_tts_with_guard = fake_guard  # type: ignore[method-assign]

    await p._handle_transcription(_stt())

    assert guard_calls == [], "plain turn was spoken twice (stream + guard)"
    assert len(fake_tts) == 1  # flush() spoke the single buffered sentence


async def test_recorder_stopped_during_stream_and_restarted(fake_tts, played) -> None:
    p = _mk()
    events: list[str] = []

    recorder = MagicMock()
    recorder.is_recording = True
    recorder.stop = AsyncMock(side_effect=lambda: events.append("stop"))
    recorder.start = AsyncMock(side_effect=lambda: events.append("start"))
    p._recorder = recorder
    p._wake_word = MagicMock()
    p._vad = MagicMock()

    async def fake_route_streaming(request, on_delta):
        events.append("stream")
        await on_delta("Привет, сэр.")
        return LLMResponse(text="Привет, сэр.", tool_calls=None,
                           provider_used="openai", latency_ms=0)

    p._llm.route_streaming = fake_route_streaming  # type: ignore[method-assign]

    await p._handle_transcription(_stt())

    assert events[0] == "stop" and events[-1] == "start"
    p._wake_word.reset.assert_called()
    p._vad.reset.assert_called()
