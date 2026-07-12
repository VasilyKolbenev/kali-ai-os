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


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    """Return True if ``text`` contains any of ``words`` as a whole word.

    Whole-word (``\\b``) matching prevents a short confirmation token like «да»
    from matching inside «даже», which previously triggered an unintended
    deploy on «даже не думай».

    Args:
        text: The transcribed utterance to scan.
        words: Candidate whole words to look for (case-insensitive).

    Returns:
        True if any candidate appears as a standalone word.
    """
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in words)


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
        # Strong reference to the background loop task. Without it the task can
        # be garbage-collected and silently cancelled mid-run, killing capture.
        self._main_loop_task: asyncio.Task[None] | None = None

        # Components (lazy-initialized)
        self._recorder = AudioRecorder()
        self._vad = VoiceActivityDetector(threshold=voice_config.vad_threshold)
        self._wake_word = WakeWordDetector(wake_word=voice_config.wake_word)
        self._stt = SpeechToText(model_size=voice_config.stt_model)
        self._llm = LLMRouter(llm_config)

        self._active_builder_session: str | None = None
        self._awaiting_deploy_confirm: bool = False

        # Audio buffer for collecting speech
        self._audio_buffer: list[np.ndarray] = []
        self._speech_active = False
        self._wake_detected = False
        self._wake_time: float = 0.0
        self._silence_count = 0
        # End an utterance after 900 ms of silence (28 chunks x 32 ms) — the
        # Rust path already lives with 960 ms (config.rs). 2026-06 raised this
        # to 2500 because ~1 s cut people off mid-thought; 2026-07-12 latency
        # sprint brings it back down as the single largest TTFA cost (+1.6 s).
        # Revert without a rebuild: KALI_SILENCE_MS=2500.
        import os as _os
        _silence_ms = int(_os.environ.get("KALI_SILENCE_MS", "900"))
        self._max_silence_chunks = max(1, _silence_ms // 32)

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
        await self._publish_pipeline_status(active=True)
        logger.info("Voice pipeline started (mode=%s)", self.mode)
        # Retain a strong reference so the GC cannot cancel the loop mid-run.
        self._main_loop_task = asyncio.create_task(self._main_loop())
        self._main_loop_task.add_done_callback(self._on_main_loop_done)

    def _on_main_loop_done(self, task: asyncio.Task[None]) -> None:
        """Log an unexpected main-loop exit (a clean cancel is not an error)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Voice pipeline main loop exited unexpectedly", exc_info=exc)

    async def stop(self) -> None:
        """Stop the voice pipeline and audio capture."""
        self._started = False
        if self._main_loop_task is not None:
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                pass
            self._main_loop_task = None
        await self._recorder.stop()
        self._reset_wake_state()
        await self._set_state(PipelineState.IDLE)
        await self._publish_pipeline_status(active=False)
        logger.info("Voice pipeline stopped")

    async def _publish_pipeline_status(self, *, active: bool) -> None:
        """Notify subscribers that the background listening state changed.

        The UI uses this to differentiate "pipeline off" (Jarvis silent) from
        "pipeline on, idle" (Jarvis listening for wake-word in the background).
        """
        await self._bus.publish(
            Event(
                topic="voice.pipeline",
                source="voice-pipeline",
                payload={"active": active, "mode": self.mode},
            )
        )

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
        text = stt_result.text
        flow = getattr(self._app_state, "builder_flow", None) if self._app_state else None

        # 1. Deploy confirmation — highest priority
        if self._awaiting_deploy_confirm and flow and self._active_builder_session:
            # Whole-word matching: a substring check fired «да» inside «даже»
            # («даже не думай» triggered an unintended deploy). Ambiguous input
            # (both a yes AND a no word) re-asks rather than defaulting to deploy.
            positive = _has_word(text, ("да", "запускай", "давай", "ок", "поехали"))
            negative = _has_word(text, ("нет", "отмени", "переделай"))
            # Unclear / ambiguous (neither, or both) → re-ask WITHOUT clearing the
            # confirm state, so the next utterance is still treated as the answer.
            if positive == negative:
                await self._speak("Не понял. Запускать? Скажи да или нет.")
                return
            try:
                if positive:
                    result = await flow.deploy(self._active_builder_session)
                    await self._speak(f"Готово! Агент {result.get('name', '')} запущен.")
                else:
                    flow.cancel(self._active_builder_session)
                    await self._speak("Отменил. Попробуем ещё раз?")
            except Exception:
                logger.exception("Builder deploy/cancel failed")
            finally:
                self._awaiting_deploy_confirm = False
                self._active_builder_session = None
            await self._set_state(PipelineState.IDLE)
            return

        # 2. Active wizard — continue answering
        if self._active_builder_session and flow:
            try:
                result = flow.answer(self._active_builder_session, text)
                if result.get("done"):
                    preview = result["preview"]
                    confirm_text = (
                        f"Я создам {preview['name']}. "
                        f"{preview.get('description', '')}. Запускать?"
                    )
                    await self._speak(confirm_text)
                    self._awaiting_deploy_confirm = True
                else:
                    await self._speak(result["question"])
                await self._set_state(PipelineState.IDLE)
                return
            except Exception:
                logger.exception("Builder answer failed — resetting session")
                self._active_builder_session = None
                # fall through to normal LLM

        # 3. New builder flow trigger
        if _detect_builder_trigger(text):
            logger.info("Builder trigger detected: %r", text)
            if flow:
                try:
                    result = flow.start(text)
                    self._active_builder_session = result["session_id"]
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

        # Long-term memory — mirrors remote_pipeline so desktop voice, mobile
        # voice and chat share ONE memory: known facts prime the system
        # prompt, and new permanent facts are extracted fire-and-forget.
        # Before this wiring the desktop voice path neither read nor wrote
        # facts — Jarvis "forgot" voice users between sessions.
        lt_memory = (
            getattr(self._app_state, "long_term_memory", None)
            if self._app_state
            else None
        )
        system_prompt = None
        if lt_memory:
            try:
                facts_context = await lt_memory.get_user_context_string()
            except Exception:
                facts_context = ""
            if facts_context:
                from kernel.jarvis_persona import get_prompt
                system_prompt = get_prompt() + "\n\n" + facts_context

        request = LLMRequest(
            text=stt_result.text,
            context=self._context[-10:],
            available_tools=self._live_tools(),
            system_prompt=system_prompt,
        )
        response = await self._llm.route(request)

        if lt_memory:
            try:
                await lt_memory.maybe_extract_and_save_facts(stt_result.text)
            except Exception as e:
                logger.warning("Background memory extraction failed: %s", e)

        # If the model asked for tools, EXECUTE them (shared path with chat) and
        # speak the combined result — previously only the first call ran (and
        # earlier none did), so multi-intent spoken commands lost work.
        final_text = response.text
        if response.tool_calls and self._app_state is not None:
            from kernel.tool_dispatch import execute_tool_calls

            try:
                dispatched = await execute_tool_calls(
                    self._app_state,
                    self._llm,
                    response.tool_calls,
                    self._context[-10:],
                    stt_result.text,
                )
            except Exception:
                logger.exception("Voice pipeline: tool dispatch failed")
                dispatched = None
            if dispatched is not None:
                final_text = dispatched[0]

        await self._bus.publish(
            Event(
                topic="agent.response",
                source="voice-pipeline",
                payload={
                    "text": final_text,
                    "provider": response.provider_used,
                    "tool_calls": None,
                    "latency_ms": response.latency_ms,
                },
            )
        )

        self._context.append({"role": "user", "content": stt_result.text})
        self._context.append({"role": "assistant", "content": final_text})

        if final_text:
            await self._play_tts_with_guard(final_text)

        await self._set_state(PipelineState.IDLE)

    def _live_tools(self) -> list[dict[str, Any]]:
        """Read the current tool palette from the registry each turn so an agent
        created or installed mid-session is callable by voice (chat already
        re-reads per request). Falls back to the startup snapshot if unavailable.
        """
        state = self._app_state
        registry = getattr(state, "plugin_registry", None) if state is not None else None
        if registry is not None:
            try:
                return registry.get_all_tools()
            except Exception:
                return self._tools
        return self._tools

    async def _speak(self, text: str) -> None:
        """Synthesize and play text through the active TTS provider."""
        await self._play_tts_with_guard(text)

    async def _play_tts_with_guard(self, text: str) -> None:
        """Play TTS through speakers with microphone anti-echo protection.

        Stops the recorder for the duration of playback, then resumes after a
        short drain buffer. Resets wake-word, VAD, and the pipeline audio
        buffer so residual echo cannot trigger a false wake or be treated as
        new speech. Always returns the pipeline to IDLE on completion.
        """
        was_recording = self._recorder.is_recording
        await self._set_state(PipelineState.SPEAKING)
        if was_recording:
            await self._recorder.stop()
        queue: asyncio.Queue[tuple[np.ndarray, int] | None] = asyncio.Queue()

        async def generate_task() -> None:
            try:
                async for audio, sr in tts_router.generate_audio_by_sentence(text):
                    if len(audio) > 0:
                        await queue.put((audio, sr))
            except Exception:
                logger.exception("TTS stream generation failed")
            finally:
                await queue.put(None)

        gen_task = asyncio.create_task(generate_task())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                audio, sr = item
                await asyncio.to_thread(_play_audio, audio, sr)
        except Exception:
            logger.exception("TTS playback failed")
        finally:
            await gen_task
            # 500ms buffer — lets speaker audio fully drain before mic resumes.
            # Without this, STT picks up room echo of JARVIS's own voice.
            await asyncio.sleep(0.5)
            if was_recording:
                await self._recorder.start()
            self._wake_word.reset()
            self._vad.reset()
            self._audio_buffer.clear()
            self._silence_count = 0
            self._speech_active = False
            await self._set_state(PipelineState.IDLE)
