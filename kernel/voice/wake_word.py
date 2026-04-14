"""Wake word detection using OpenWakeWord."""

import logging
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class WakeWordResult:
    """Result of wake word detection."""

    detected: bool
    word: str | None
    confidence: float


class WakeWordDetector:
    """Detects wake word in audio using OpenWakeWord.

    Falls back to always-false when model is not loaded.
    """

    def __init__(self, wake_word: str = "jarvis", threshold: float = 0.5) -> None:
        self.wake_word = wake_word
        self.threshold = threshold
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the OpenWakeWord model."""
        try:
            from openwakeword.model import Model

            self._model = Model()
            self._loaded = True
            logger.info("OpenWakeWord model loaded for '%s'", self.wake_word)
        except Exception as e:
            logger.warning("Failed to load OpenWakeWord: %s", e)
            self._loaded = False

    def process(self, audio: np.ndarray) -> WakeWordResult:
        """Process audio chunk and detect wake word.

        Args:
            audio: Float32 audio samples, typically 16kHz mono.

        Returns:
            WakeWordResult with detection status and confidence.
        """
        if self._model is None:
            return WakeWordResult(detected=False, word=None, confidence=0.0)

        audio_int16 = (audio * 32767).astype(np.int16)
        prediction = self._model.predict(audio_int16)  # type: ignore[union-attr]

        for model_name, score in prediction.items():
            if score >= self.threshold:
                logger.info("Wake word detected: %s (score=%.2f)", model_name, score)
                return WakeWordResult(detected=True, word=model_name, confidence=float(score))

        return WakeWordResult(detected=False, word=None, confidence=0.0)

    def reset(self) -> None:
        """Reset internal model state between utterances."""
        if self._model is not None and hasattr(self._model, "reset"):
            self._model.reset()  # type: ignore[union-attr]
