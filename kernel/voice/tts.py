"""Text-to-Speech using Piper TTS."""

import logging
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Result of text-to-speech synthesis."""

    audio: np.ndarray
    sample_rate: int = 22050
    duration_ms: int = 0

    @property
    def is_empty(self) -> bool:
        return len(self.audio) == 0

    @classmethod
    def empty(cls) -> "TTSResult":
        return cls(audio=np.array([], dtype=np.float32), sample_rate=22050, duration_ms=0)


class TextToSpeech:
    """Synthesizes speech from text using Piper TTS.

    Model is lazy-loaded. Returns empty audio when no model is available.
    """

    def __init__(self, voice: str = "default", speaker_id: int | None = None) -> None:
        self.voice = voice
        self.speaker_id = speaker_id
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        try:
            from piper import PiperVoice  # noqa: F401

            logger.info("Attempting to load Piper voice: %s", self.voice)
            self._loaded = False
            logger.warning("Piper TTS model not configured, TTS disabled")
        except ImportError:
            logger.warning("piper-tts not installed, TTS disabled")
            self._loaded = False

    def synthesize(self, text: str) -> TTSResult:
        if not text.strip() or self._model is None:
            return TTSResult.empty()

        start = time.perf_counter()
        try:
            audio_parts: list[np.ndarray] = []
            for audio_bytes in self._model.synthesize_stream_raw(text):  # type: ignore[attr-defined]
                chunk = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                audio_parts.append(chunk)

            if not audio_parts:
                return TTSResult.empty()

            audio = np.concatenate(audio_parts)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "TTS: %d chars -> %.1fs audio (%.0fms)",
                len(text),
                len(audio) / 22050,
                elapsed_ms,
            )
            return TTSResult(audio=audio, sample_rate=22050, duration_ms=elapsed_ms)
        except Exception:
            logger.exception("TTS synthesis failed")
            return TTSResult.empty()

    def play(self, result: TTSResult) -> None:
        if result.is_empty:
            return
        try:
            import sounddevice as sd

            sd.play(result.audio, result.sample_rate)
            sd.wait()
        except Exception:
            logger.exception("Failed to play audio")
