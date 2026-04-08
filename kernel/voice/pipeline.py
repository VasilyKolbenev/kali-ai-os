"""Voice pipeline orchestrator — chains recorder, VAD, wake word, STT, LLM, TTS."""

import asyncio
import logging
from enum import Enum
from typing import Any

import numpy as np

from kernel.event_bus import EventBus
from kernel.llm_router import LLMRequest, LLMRouter
from kernel.models import Event, LLMConfig, VoiceConfig
from kernel.voice.recorder import AudioChunk, AudioRecorder
from kernel.voice.stt import SpeechToText, STTResult
from kernel.voice.tts import TextToSpeech
from kernel.voice.vad import VoiceActivityDetector
from kernel.voice.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """Current state of the voice pipeline."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class VoicePipeline:
    """Orchestrates the full voice interaction flow.

    Modes:
    - wake_word: listens for wake word, then transcribes
    - push_to_talk: transcribes on demand (via event)
    - continuous: always transcribing
    """

    def __init__(
        self,
        event_bus: EventBus,
        voice_config: VoiceConfig,
        llm_config: LLMConfig,
        tools: list[dict[str, Any]],
    ) -> None:
        self._bus = event_bus
        self._voice_config = voice_config
        self._tools = tools
        self._state = PipelineState.IDLE
        self._context: list[dict[str, Any]] = []

        # Components (lazy-initialized)
        self._recorder = AudioRecorder()
        self._vad = VoiceActivityDetector(threshold=voice_config.vad_threshold)
        self._wake_word = WakeWordDetector(wake_word=voice_config.wake_word)
        self._stt = SpeechToText(model_size=voice_config.stt_model)
        self._tts = TextToSpeech(voice=voice_config.tts_voice)
        self._llm = LLMRouter(llm_config)

        # Audio buffer for collecting speech
        self._audio_buffer: list[np.ndarray] = []
        self._speech_active = False
        self._wake_detected = False
        self._silence_count = 0
        self._max_silence_chunks = 30  # ~1s of silence ends utterance

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def mode(self) -> str:
        return self._voice_config.mode

    async def _set_state(self, new_state: PipelineState) -> None:
        """Transition to a new state and publish state change event.

        Args:
            new_state: The target pipeline state.
        """
        if self._state == new_state:
            return
        self._state = new_state
        await self._bus.publish(
            Event(
                topic="voice.state",
                source="voice-pipeline",
                payload={"state": new_state.value},
            )
        )

    def load_models(self) -> None:
        """Load all voice models synchronously."""
        logger.info("Loading voice models...")
        self._vad.load()
        self._wake_word.load()
        self._stt.load()
        self._tts.load()
        logger.info("Voice models loaded")

    async def start(self) -> None:
        """Start the voice pipeline and begin audio capture."""
        await self._recorder.start()
        await self._set_state(PipelineState.IDLE)
        logger.info("Voice pipeline started (mode=%s)", self.mode)
        asyncio.create_task(self._main_loop())

    async def stop(self) -> None:
        """Stop the voice pipeline and audio capture."""
        await self._recorder.stop()
        await self._set_state(PipelineState.IDLE)
        logger.info("Voice pipeline stopped")

    async def _main_loop(self) -> None:
        while self._recorder.is_recording:
            try:
                chunk = await asyncio.wait_for(self._recorder.read_chunk(), timeout=1.0)
                await self.process_chunk(chunk)
            except asyncio.TimeoutError:
                continue
            except Exception:
                logger.exception("Pipeline loop error")

    async def process_chunk(self, chunk: AudioChunk) -> None:
        """Process a single audio chunk through the pipeline.

        Args:
            chunk: Audio chunk to process.
        """
        vad_result = self._vad.process(chunk.data, chunk.sample_rate)

        if self.mode == "wake_word":
            await self._process_wake_word_mode(chunk, vad_result)
        elif self.mode == "continuous":
            await self._process_continuous_mode(chunk, vad_result)

    async def _process_wake_word_mode(self, chunk: AudioChunk, vad_result: Any) -> None:
        if not self._wake_detected:
            ww_result = self._wake_word.process(chunk.data)
            if ww_result.detected:
                self._wake_detected = True
                self._audio_buffer.clear()
                self._silence_count = 0
                await self._set_state(PipelineState.LISTENING)
                await self._bus.publish(
                    Event(
                        topic="voice.wake_word",
                        source="voice-pipeline",
                        payload={"word": ww_result.word},
                    )
                )
        else:
            if vad_result.is_speech:
                self._audio_buffer.append(chunk.data)
                self._silence_count = 0
            else:
                self._silence_count += 1

            if self._silence_count >= self._max_silence_chunks and self._audio_buffer:
                await self._process_utterance()
                self._wake_detected = False
                self._audio_buffer.clear()

    async def _process_continuous_mode(self, chunk: AudioChunk, vad_result: Any) -> None:
        if vad_result.is_speech:
            self._audio_buffer.append(chunk.data)
            self._silence_count = 0
            if self._state == PipelineState.IDLE:
                await self._set_state(PipelineState.LISTENING)
        else:
            self._silence_count += 1

        if self._silence_count >= self._max_silence_chunks and self._audio_buffer:
            await self._process_utterance()
            self._audio_buffer.clear()

    async def _process_utterance(self) -> None:
        if not self._audio_buffer:
            return

        audio = np.concatenate(self._audio_buffer)
        await self._set_state(PipelineState.THINKING)

        stt_result = self._stt.transcribe(audio)
        if stt_result.is_empty:
            await self._set_state(PipelineState.IDLE)
            return

        await self._handle_transcription(stt_result)

    async def _handle_transcription(self, stt_result: STTResult) -> None:
        """Handle a completed transcription: publish event, call LLM, and speak response.

        Args:
            stt_result: The transcription result to handle.
        """
        await self._bus.publish(
            Event(
                topic="voice.transcribed",
                source="voice-pipeline",
                payload={
                    "text": stt_result.text,
                    "language": stt_result.language,
                    "confidence": stt_result.confidence,
                    "duration_ms": stt_result.duration_ms,
                },
            )
        )

        request = LLMRequest(
            text=stt_result.text,
            context=self._context[-10:],
            available_tools=self._tools,
        )
        response = await self._llm.route(request)

        tool_calls_payload = (
            [{"name": tc.name, "args": tc.arguments} for tc in response.tool_calls]
            if response.tool_calls
            else None
        )
        await self._bus.publish(
            Event(
                topic="agent.response",
                source="voice-pipeline",
                payload={
                    "text": response.text,
                    "provider": response.provider_used,
                    "tool_calls": tool_calls_payload,
                    "latency_ms": response.latency_ms,
                },
            )
        )

        self._context.append({"role": "user", "content": stt_result.text})
        self._context.append({"role": "assistant", "content": response.text})

        if response.text:
            await self._set_state(PipelineState.SPEAKING)
            tts_result = self._tts.synthesize(response.text)
            if not tts_result.is_empty:
                self._tts.play(tts_result)

        await self._set_state(PipelineState.IDLE)
