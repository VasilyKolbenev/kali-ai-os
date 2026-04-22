"""Voice pipeline orchestrator — chains recorder, VAD, wake word, STT, LLM, TTS."""

import asyncio
import logging
import re
import time
from enum import Enum
from typing import Any

import numpy as np

from kernel.event_bus import EventBus
from kernel.llm_router import LLMRequest, LLMRouter
from kernel.models import Event, LLMConfig, VoiceConfig
from kernel.voice import tts_router
from kernel.voice.recorder import AudioChunk, AudioRecorder
from kernel.voice.stt import SpeechToText, STTResult
from kernel.voice.vad import VoiceActivityDetector
from kernel.voice.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)

_BUILDER_TRIGGER_PATTERNS = [
    r"созда[йи].*агент",
    r"сделай.*агент",
    r"созда[йи].*скилл",
    r"сделай.*скилл",
    r"построй.*агент",
]


def _detect_builder_trigger(text: str) -> bool:
    """Return True if transcribed text should start a builder flow.

    Matches Russian patterns: "создай агента", "сделай скилл", "построй агента".
    Case-insensitive.
    """
    if not text:
        return False
    lowered = text.lower().strip()
    return any(re.search(p, lowered) for p in _BUILDER_TRIGGER_PATTERNS)


# Timeout: reset LISTENING → IDLE if no speech after wake word
_LISTEN_TIMEOUT_S = 3.0
# Minimum speech chunks before we try STT (avoid noise triggers)
_MIN_SPEECH_CHUNKS = 5


def _play_audio(audio: np.ndarray, sr: int) -> None:
    """Play audio through system speakers via sounddevice."""
    try:
        import sounddevice as sd

        sd.play(audio, sr)
        sd.wait()
    except Exception:
        logger.exception("Failed to play audio")


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
        app_state: Any = None,
    ) -> None:
        self._bus = event_bus
        self._voice_config = voice_config
        self._tools = tools
        self._app_state = app_state
        self._state = PipelineState.IDLE
        self._context: list[dict[str, Any]] = []
        self._started = False

        # Components (lazy-initialized)
        self._recorder = AudioRecorder()
        self._vad = VoiceActivityDetector(threshold=voice_config.vad_threshold)
        self._wake_word = WakeWordDetector(wake_word=voice_config.wake_word)
        self._stt = SpeechToText(model_size=voice_config.stt_model)
        self._llm = LLMRouter(llm_config)

        # Audio buffer for collecting speech
        self._audio_buffer: list[np.ndarray] = []
        self._speech_active = False
        self._wake_detected = False
        self._wake_time: float = 0.0
        self._silence_count = 0
        self._max_silence_chunks = 30  # ~1s of silence ends utterance

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def mode(self) -> str:
        return self._voice_config.mode

    @property
    def is_started(self) -> bool:
        return self._started

    async def _set_state(self, new_state: PipelineState) -> None:
        """Transition to a new state and publish state change event."""
        if self._state == new_state:
            return
        old = self._state
        self._state = new_state
        logger.info("Pipeline: %s -> %s", old.value, new_state.value)
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
        tts_router.load_models()
        logger.info("Voice models loaded")

    async def start(self) -> None:
        """Start the voice pipeline and begin audio capture.

        Idempotent — safe to call multiple times.
        """
        if self._started:
            logger.info("Voice pipeline already running, skipping start")
            return
        self._started = True
        await self._recorder.start()
        await self._set_state(PipelineState.IDLE)
        logger.info("Voice pipeline started (mode=%s)", self.mode)
        asyncio.create_task(self._main_loop())

    async def stop(self) -> None:
        """Stop the voice pipeline and audio capture."""
        self._started = False
        await self._recorder.stop()
        self._reset_wake_state()
        await self._set_state(PipelineState.IDLE)
        logger.info("Voice pipeline stopped")

    def _reset_wake_state(self) -> None:
        """Reset wake word and listening state."""
        self._wake_detected = False
        self._wake_time = 0.0
        self._audio_buffer.clear()
        self._silence_count = 0

    async def _main_loop(self) -> None:
        logger.info("Pipeline main loop started")
        while self._started and self._recorder.is_recording:
            try:
                chunk = await self._recorder.read_chunk()
                await self.process_chunk(chunk)
            except Exception:
                logger.exception("Pipeline loop error")
                await asyncio.sleep(0.1)
        logger.info("Pipeline main loop exited")

    async def process_chunk(self, chunk: AudioChunk) -> None:
        """Process a single audio chunk through the pipeline."""
        # Skip processing during THINKING/SPEAKING states
        if self._state in (PipelineState.THINKING, PipelineState.SPEAKING):
            return

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
                self._wake_time = time.monotonic()
                self._audio_buffer.clear()
                self._silence_count = 0
                logger.info("Wake word! Listening for command...")
                await self._set_state(PipelineState.LISTENING)
                await self._bus.publish(
                    Event(
                        topic="voice.wake_word",
                        source="voice-pipeline",
                        payload={"word": ww_result.word},
                    )
                )
        else:
            # Check listen timeout
            elapsed = time.monotonic() - self._wake_time
            if elapsed > _LISTEN_TIMEOUT_S:
                logger.info(
                    "Listen timeout (%.1fs) — no speech, resetting to IDLE", elapsed
                )
                self._reset_wake_state()
                await self._set_state(PipelineState.IDLE)
                return

            if vad_result.is_speech:
                self._audio_buffer.append(chunk.data)
                self._silence_count = 0
                self._speech_active = True
            else:
                self._silence_count += 1

            # Only process utterance after we've heard actual speech + silence
            if (
                self._silence_count >= self._max_silence_chunks
                and len(self._audio_buffer) >= _MIN_SPEECH_CHUNKS
                and self._speech_active
            ):
                await self._process_utterance()
                self._reset_wake_state()

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
        duration_s = len(audio) / 16000
        logger.info("Processing utterance: %.1fs of audio", duration_s)
        await self._set_state(PipelineState.THINKING)

        stt_result = self._stt.transcribe(audio)
        if stt_result.is_empty:
            logger.info("STT returned empty — ignoring")
            await self._set_state(PipelineState.IDLE)
            return

        logger.info("STT: '%s' (lang=%s, conf=%.2f)", stt_result.text, stt_result.language, stt_result.confidence)
        await self._handle_transcription(stt_result)

    async def _handle_transcription(self, stt_result: STTResult) -> None:
        """Handle a completed transcription: publish event, call LLM, and speak response."""
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

        if _detect_builder_trigger(stt_result.text):
            logger.info("Builder trigger detected: %r", stt_result.text)
            flow = getattr(self._app_state, "builder_flow", None) if self._app_state else None
            if flow:
                try:
                    result = flow.start(stt_result.text)
                    await self._speak(result["question"])
                    await self._bus.publish(
                        Event(
                            topic="builder.started",
                            source="voice-pipeline",
                            payload={
                                "session_id": result["session_id"],
                                "question": result["question"],
                            },
                        )
                    )
                    await self._set_state(PipelineState.IDLE)
                    return
                except Exception:
                    logger.exception("Builder flow start failed — falling back to normal LLM")

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
            # Anti-echo: stop mic while speaking to avoid self-recording
            await self._recorder.stop()
            try:
                audio, sr = await asyncio.to_thread(
                    tts_router.generate_audio, response.text
                )
                if len(audio) > 0:
                    await asyncio.to_thread(_play_audio, audio, sr)
            except Exception:
                logger.exception("TTS playback failed")
            finally:
                # 500ms buffer — lets speaker audio fully drain before mic resumes.
                # Without this, STT picks up room echo of JARVIS's own voice.
                await asyncio.sleep(0.5)
                await self._recorder.start()
                self._wake_word.reset()
                self._vad.reset()

        await self._set_state(PipelineState.IDLE)

    async def _speak(self, text: str) -> None:
        """Synthesize and play text through the active TTS provider."""
        try:
            audio, sr = await asyncio.to_thread(tts_router.generate_audio, text)
            if len(audio) > 0:
                await asyncio.to_thread(_play_audio, audio, sr)
        except Exception:
            logger.exception("TTS speak failed")
