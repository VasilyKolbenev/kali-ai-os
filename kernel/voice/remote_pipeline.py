"""Remote voice pipeline for handling WebSocket audio streams from mobile clients."""

import asyncio
import base64
import logging
from typing import Any

import numpy as np

from kernel.event_bus import EventBus
from kernel.llm_router import LLMRequest, LLMRouter
from kernel.models import Event, LLMConfig, VoiceConfig
from kernel.voice import tts_router
from kernel.voice.pipeline import PipelineState
from kernel.voice.stt import SpeechToText

logger = logging.getLogger(__name__)

# Cap the per-utterance audio buffer to bound memory from a flooding WS client.
# 16 kHz int16 PCM is ~32 KB/s, so 50 MB is ~26 min of audio — far beyond any real
# voice command, but prevents an unbounded buffer from a client that streams
# 'voice.audio_stream' chunks without ever sending 'voice.state=idle' (OOM DoS
# over the intentionally LAN-bound /ws endpoint).
MAX_AUDIO_BUFFER_BYTES = 50 * 1024 * 1024


class RemoteVoicePipeline:
    """Handles voice interactions originating from a remote WebSocket client.
    
    Subscribes to 'voice.state' and 'voice.audio_stream' from the event bus.
    Sends responses via 'voice.tts_chunk'.
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
        
        self._llm = LLMRouter(llm_config)
        self._context: list[dict[str, Any]] = []
        
        self._audio_buffer: list[np.ndarray] = []
        self._audio_buffer_bytes = 0
        self._state = PipelineState.IDLE
        
        # Subscribe to websocket events
        self._bus.subscribe("voice.state", self._on_voice_state)
        self._bus.subscribe("voice.audio_stream", self._on_audio_stream)

    async def _on_voice_state(self, event: Event) -> None:
        if event.source != "websocket":
            return
            
        state_str = event.payload.get("state")
        print(f"DEBUG: _on_voice_state received: {state_str}")
        if state_str == "listening":
            print("DEBUG: Client started listening")
            self._audio_buffer.clear()
            self._audio_buffer_bytes = 0
            self._state = PipelineState.LISTENING
        elif state_str == "idle" and self._state == PipelineState.LISTENING:
            print("DEBUG: Client stopped listening, processing utterance...")
            self._state = PipelineState.THINKING
            asyncio.create_task(self._process_utterance())

    async def _on_audio_stream(self, event: Event) -> None:
        if event.source != "websocket" or self._state != PipelineState.LISTENING:
            return
            
        chunk_b64 = event.payload.get("audio") or event.payload.get("chunk")
        if chunk_b64:
            try:
                raw_bytes = base64.b64decode(chunk_b64)
            except Exception as e:
                print(f"DEBUG: Failed to decode audio chunk: {e}")
                return
            # Bound memory: an untrusted LAN /ws client could stream chunks forever
            # without sending voice.state=idle. Drop the utterance past the cap
            # instead of growing the buffer until the process OOMs.
            if self._audio_buffer_bytes + len(raw_bytes) > MAX_AUDIO_BUFFER_BYTES:
                logger.warning(
                    "Remote audio buffer exceeded %d bytes — dropping utterance and resetting to IDLE",
                    MAX_AUDIO_BUFFER_BYTES,
                )
                self._audio_buffer.clear()
                self._audio_buffer_bytes = 0
                self._state = PipelineState.IDLE
                return
            # Keep raw bytes, as web browser sends WebM/Opus chunks
            self._audio_buffer.append(raw_bytes)
            self._audio_buffer_bytes += len(raw_bytes)

    async def _process_utterance(self) -> None:
        print("DEBUG: _process_utterance called")
        if not self._audio_buffer:
            print("DEBUG: audio buffer is empty")
            self._state = PipelineState.IDLE
            return

        try:
            # The Flutter app sends raw 16kHz int16 PCM (even on Web)
            raw_audio = b"".join(self._audio_buffer)
            audio_np_int16 = np.frombuffer(raw_audio, dtype=np.int16)
            audio = audio_np_int16.astype(np.float32) / 32768.0

            if audio is None or len(audio) == 0:
                print("DEBUG: Audio decode failed or empty")
                self._state = PipelineState.IDLE
                return

            duration_s = len(audio) / 16000
            print(f"DEBUG: Processing utterance: {duration_s:.1f}s of audio")

            # STT is blocking, run in thread
            from kernel.voice.transcribe_helper import get_or_create_stt
            stt = get_or_create_stt(self._app_state)
            stt_result = await asyncio.to_thread(stt.transcribe, audio)
            print(f"DEBUG: STT result: {stt_result.text} (conf={stt_result.confidence})")
        except Exception as e:
            print(f"DEBUG: _process_utterance exception: {e}")
            import traceback
            traceback.print_exc()
            self._state = PipelineState.IDLE
            return
        
        if stt_result.is_empty:
            logger.info("Remote pipeline: STT returned empty — ignoring")
            self._state = PipelineState.IDLE
            return

        logger.info("Remote pipeline STT: '%s' (conf=%.2f)", stt_result.text, stt_result.confidence)
        
        # Send text back to UI for visibility
        await self._bus.publish(
            Event(
                topic="voice.transcribed",
                source="remote-pipeline",
                payload={
                    "text": stt_result.text,
                    "language": stt_result.language,
                    "confidence": stt_result.confidence,
                    "duration_ms": stt_result.duration_ms,
                },
            )
        )

        lt_memory = self._app_state.long_term_memory if self._app_state else None
        system_prompt = None
        if lt_memory:
            try:
                facts_context = await lt_memory.get_user_context_string()
            except Exception:
                facts_context = ""
                
            from kernel.jarvis_persona import get_prompt
            system_prompt = get_prompt() + "\n\n" + facts_context

        request = LLMRequest(
            text=stt_result.text,
            context=self._context[-10:],
            available_tools=self._tools,
            system_prompt=system_prompt,
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
                source="remote-pipeline",
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
            await self._stream_tts(response.text)

        if lt_memory:
            try:
                await lt_memory.maybe_extract_and_save_facts(stt_result.text)
            except Exception as e:
                logger.warning(f"Background memory extraction failed: {e}")

        self._state = PipelineState.IDLE

    async def _stream_tts(self, text: str) -> None:
        """Synthesize TTS and stream back to client as Base64."""
        self._state = PipelineState.SPEAKING
        logger.info("Remote pipeline: Streaming TTS...")
        
        try:
            import io
            import scipy.io.wavfile as wavfile
            
            async for audio, sr in tts_router.generate_audio_stream(text):
                if len(audio) > 0:
                    # Create a proper WAV file in memory so the client player can decode it
                    wav_io = io.BytesIO()
                    wavfile.write(wav_io, sr, audio)
                    wav_bytes = wav_io.getvalue()
                    
                    # Convert to base64
                    chunk_b64 = base64.b64encode(wav_bytes).decode("utf-8")
                    await self._bus.publish(
                        Event(
                            topic="voice.tts_chunk",
                            source="remote-pipeline",
                            payload={
                                "audio": chunk_b64,
                                "sample_rate": sr,
                            }
                        )
                    )
        except Exception:
            logger.exception("Remote pipeline: TTS stream generation failed")
            
        logger.info("Remote pipeline: TTS stream finished")
