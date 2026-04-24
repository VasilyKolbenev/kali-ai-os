"""Tests for voice pipeline orchestrator."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from kernel.event_bus import EventBus
from kernel.llm_router import LLMResponse
from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import PipelineState, VoicePipeline
from kernel.voice.recorder import AudioChunk
from kernel.voice.stt import STTResult


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def pipeline(event_bus: EventBus) -> VoicePipeline:
    voice_config = VoiceConfig()
    llm_config = LLMConfig()
    return VoicePipeline(
        event_bus=event_bus,
        voice_config=voice_config,
        llm_config=llm_config,
        tools=[],
    )


class TestPipelineState:
    def test_initial_state_is_idle(self, pipeline: VoicePipeline) -> None:
        assert pipeline.state == PipelineState.IDLE

    def test_state_enum_values(self) -> None:
        assert PipelineState.IDLE.value == "idle"
        assert PipelineState.LISTENING.value == "listening"
        assert PipelineState.THINKING.value == "thinking"
        assert PipelineState.SPEAKING.value == "speaking"


class TestVoicePipeline:
    def test_create_pipeline(self, pipeline: VoicePipeline) -> None:
        assert pipeline.state == PipelineState.IDLE
        assert pipeline.mode == "wake_word"

    async def test_process_audio_silence(self, pipeline: VoicePipeline) -> None:
        chunk = AudioChunk(data=np.zeros(512, dtype=np.float32), sample_rate=16000)
        await pipeline.process_chunk(chunk)
        assert pipeline.state == PipelineState.IDLE

    async def test_state_change_emits_event(
        self, pipeline: VoicePipeline, event_bus: EventBus
    ) -> None:
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe("voice.state", handler)
        await pipeline._set_state(PipelineState.LISTENING)

        assert len(received) == 1
        assert received[0].payload["state"] == "listening"

    async def test_transcription_emits_event(
        self, pipeline: VoicePipeline, event_bus: EventBus
    ) -> None:
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe("voice.transcribed", handler)

        # Mock LLM to avoid real network calls
        dummy_response = LLMResponse(
            text="Hello there",
            tool_calls=None,
            provider_used="mock",
            latency_ms=0,
        )
        pipeline._llm.route = AsyncMock(return_value=dummy_response)

        await pipeline._handle_transcription(
            STTResult(text="hello jarvis", language="en", confidence=0.9, duration_ms=200)
        )

        assert len(received) == 1
        assert received[0].payload["text"] == "hello jarvis"


class TestAntiEcho:
    """Verify TTS playback does not leak into the microphone input path."""

    async def test_speak_stops_recorder_during_playback(
        self, pipeline: VoicePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate active recording before _speak is called
        pipeline._recorder._recording = True
        stop_mock = AsyncMock()
        start_mock = AsyncMock()
        pipeline._recorder.stop = stop_mock
        pipeline._recorder.start = start_mock

        # Stub TTS to return a tiny non-empty audio buffer
        monkeypatch.setattr(
            "kernel.voice.pipeline.tts_router.generate_audio",
            lambda _text: (np.zeros(100, dtype=np.float32), 16000),
        )
        # Stub playback so tests don't touch real audio hardware
        monkeypatch.setattr("kernel.voice.pipeline._play_audio", lambda _a, _sr: None)
        # Skip the 500ms real sleep
        monkeypatch.setattr(
            "kernel.voice.pipeline.asyncio.sleep", AsyncMock(return_value=None)
        )

        await pipeline._speak("test")

        stop_mock.assert_awaited_once()
        start_mock.assert_awaited_once()

    async def test_speak_resets_detectors_and_buffer(
        self, pipeline: VoicePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pre-populate buffer + counters as if some audio was being accumulated
        pipeline._audio_buffer = [np.zeros(256, dtype=np.float32)]
        pipeline._silence_count = 5
        pipeline._speech_active = True
        pipeline._wake_word.reset = MagicMock()
        pipeline._vad.reset = MagicMock()

        monkeypatch.setattr(
            "kernel.voice.pipeline.tts_router.generate_audio",
            lambda _text: (np.zeros(100, dtype=np.float32), 16000),
        )
        monkeypatch.setattr("kernel.voice.pipeline._play_audio", lambda _a, _sr: None)
        monkeypatch.setattr(
            "kernel.voice.pipeline.asyncio.sleep", AsyncMock(return_value=None)
        )

        await pipeline._speak("hello")

        assert pipeline._audio_buffer == []
        assert pipeline._silence_count == 0
        assert pipeline._speech_active is False
        pipeline._wake_word.reset.assert_called_once()
        pipeline._vad.reset.assert_called_once()

    async def test_speak_transitions_through_speaking_to_idle(
        self, pipeline: VoicePipeline, monkeypatch: pytest.MonkeyPatch, event_bus: EventBus
    ) -> None:
        states_seen: list[str] = []

        async def handler(event):
            states_seen.append(event.payload["state"])

        event_bus.subscribe("voice.state", handler)

        monkeypatch.setattr(
            "kernel.voice.pipeline.tts_router.generate_audio",
            lambda _text: (np.zeros(100, dtype=np.float32), 16000),
        )
        monkeypatch.setattr("kernel.voice.pipeline._play_audio", lambda _a, _sr: None)
        monkeypatch.setattr(
            "kernel.voice.pipeline.asyncio.sleep", AsyncMock(return_value=None)
        )

        await pipeline._speak("hi")

        # Must have passed through SPEAKING and ended on IDLE
        assert "speaking" in states_seen
        assert pipeline.state == PipelineState.IDLE

    async def test_speak_does_not_restart_recorder_if_was_stopped(
        self, pipeline: VoicePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Recorder NOT active — _speak must not spuriously start it
        pipeline._recorder._recording = False
        stop_mock = AsyncMock()
        start_mock = AsyncMock()
        pipeline._recorder.stop = stop_mock
        pipeline._recorder.start = start_mock

        monkeypatch.setattr(
            "kernel.voice.pipeline.tts_router.generate_audio",
            lambda _text: (np.zeros(100, dtype=np.float32), 16000),
        )
        monkeypatch.setattr("kernel.voice.pipeline._play_audio", lambda _a, _sr: None)
        monkeypatch.setattr(
            "kernel.voice.pipeline.asyncio.sleep", AsyncMock(return_value=None)
        )

        await pipeline._speak("test")

        stop_mock.assert_not_awaited()
        start_mock.assert_not_awaited()
