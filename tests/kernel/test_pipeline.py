"""Tests for voice pipeline orchestrator."""

from unittest.mock import AsyncMock

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
