"""Speech-to-Text using faster-whisper (CTranslate2)."""

import logging
import time
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class STTResult:
    """Result of speech-to-text transcription."""

    text: str
    language: str | None
    confidence: float
    duration_ms: int

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) == 0


class SpeechToText:
    """Transcribes audio to text using faster-whisper.

    Model is lazy-loaded. Without model, returns empty results.
    """

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        self.model_size = model_size
        self._device = device
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the Whisper model via faster-whisper."""
        import os

        # Use project-local HF cache to avoid Windows symlink issues
        hf_cache = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", ".hf_cache",
        )
        os.makedirs(hf_cache, exist_ok=True)
        os.environ.setdefault("HF_HOME", hf_cache)
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        try:
            from faster_whisper import WhisperModel

            # Auto-detect GPU: try CUDA first, fallback to CPU
            device = "cpu"
            compute_type = "float32"
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
            except ImportError:
                pass

            self._model = WhisperModel(
                self.model_size,
                device=device,
                compute_type=compute_type,
            )
            self._loaded = True
            logger.info("Whisper model loaded: %s (%s/%s)", self.model_size, device, compute_type)
        except Exception as e:
            logger.warning("Failed to load Whisper model: %s", e)
            self._loaded = False

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> STTResult:
        """Transcribe audio to text.

        Args:
            audio: Float32 audio samples.
            sample_rate: Sample rate in Hz (default 16000).

        Returns:
            STTResult with transcription text and metadata.
        """
        if self._model is None:
            return STTResult(text="", language=None, confidence=0.0, duration_ms=0)

        start = time.perf_counter()
        segments, info = self._model.transcribe(  # type: ignore[union-attr]
            audio,
            beam_size=5,
            language="ru",
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text_parts = [segment.text.strip() for segment in segments]
        text = " ".join(text_parts).strip()
        
        # Drop common Whisper hallucinations from silence/noise
        lower_text = text.lower()
        if any(phrase in lower_text for phrase in [
            "субтитр", "редактор", "корректор", "а на этом у меня всё",
            "спасибо за просмотр"
        ]):
            text = ""
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info("STT: '%s' (lang=%s, %.0fms)", text, info.language, elapsed_ms)
        return STTResult(
            text=text,
            language=info.language,
            confidence=info.language_probability,
            duration_ms=elapsed_ms,
        )
