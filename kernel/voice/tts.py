"""Text-to-Speech via Silero + RVC ONNX microservice pipeline."""

import io
import logging
import os
import time
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TTS_URL = os.environ.get("TTS_URL", "http://localhost:3002")


@dataclass
class TTSResult:
    """Result of text-to-speech synthesis."""

    audio: np.ndarray
    sample_rate: int = 24000
    duration_ms: int = 0

    @property
    def is_empty(self) -> bool:
        return len(self.audio) == 0

    @classmethod
    def empty(cls) -> "TTSResult":
        return cls(audio=np.array([], dtype=np.float32), sample_rate=24000, duration_ms=0)


class TextToSpeech:
    """Synthesizes speech via Silero + RVC ONNX JARVIS voice pipeline.

    Connects to TTS microservice (services/tts/server.py) which handles:
    - Silero TTS text-to-speech
    - RVC ONNX voice conversion to JARVIS voice (DirectML GPU)
    """

    def __init__(self, voice: str = "jarvis", speaker_id: int | None = None) -> None:
        self.voice = voice
        self.speaker_id = speaker_id
        self._loaded = False
        self._base_url = TTS_URL

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Check if TTS service is available."""
        try:
            import requests

            r = requests.get(f"{self._base_url}/health", timeout=5)
            if r.status_code == 200:
                info = r.json()
                self._loaded = info.get("loaded", False)
                logger.info(
                    "TTS service connected: engine=%s, rvc=%s",
                    info.get("engine"),
                    info.get("rvc"),
                )
            else:
                logger.warning("TTS service returned %d", r.status_code)
                self._loaded = False
        except Exception:
            logger.warning("TTS service not available at %s", self._base_url)
            self._loaded = False

    def synthesize(self, text: str, language: str | None = None) -> TTSResult:
        """Synthesize speech from text via TTS microservice."""
        if not text.strip():
            return TTSResult.empty()

        start = time.perf_counter()
        try:
            import requests
            import soundfile as sf

            payload: dict = {"text": text}
            if language:
                payload["language"] = language

            r = requests.post(
                f"{self._base_url}/synthesize",
                json=payload,
                timeout=30,
            )

            if r.status_code != 200:
                logger.error("TTS service error %d: %s", r.status_code, r.text[:100])
                return TTSResult.empty()

            buf = io.BytesIO(r.content)
            audio, sr = sf.read(buf)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "TTS: %d chars -> %.1fs audio (%dms)",
                len(text),
                len(audio) / sr,
                elapsed_ms,
            )
            return TTSResult(audio=audio, sample_rate=sr, duration_ms=elapsed_ms)

        except Exception:
            logger.exception("TTS synthesis failed")
            return TTSResult.empty()

    def play(self, result: TTSResult) -> None:
        """Play audio result through speakers."""
        if result.is_empty:
            return
        try:
            import sounddevice as sd

            sd.play(result.audio, result.sample_rate)
            sd.wait()
        except Exception:
            logger.exception("Failed to play audio")
