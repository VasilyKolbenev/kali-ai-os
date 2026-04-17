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

    Buffers small audio chunks to meet OpenWakeWord's 1280-sample minimum.
    Falls back to always-false when model is not loaded.
    """

    # OpenWakeWord expects >= 1280 samples (80ms at 16kHz)
    _MIN_SAMPLES = 1280

    def __init__(self, wake_word: str = "jarvis", threshold: float = 0.3) -> None:
        self.wake_word = wake_word
        self.threshold = threshold
        self._model: object | None = None
        self._loaded = False
        self._buffer: list[np.ndarray] = []
        self._buffer_len = 0
        self._debug_counter = 0

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the OpenWakeWord model."""
        try:
            from openwakeword.model import Model

            self._model = Model()
            self._loaded = True
            # Log available models
            if hasattr(self._model, "models") and self._model.models:
                names = list(self._model.models.keys())
                logger.info("OpenWakeWord loaded models: %s", names)
            logger.info(
                "OpenWakeWord ready (wake_word=%s, threshold=%.2f)",
                self.wake_word, self.threshold,
            )
        except Exception as e:
            logger.warning("Failed to load OpenWakeWord: %s", e)
            self._loaded = False

    def process(self, audio: np.ndarray) -> WakeWordResult:
        """Process audio chunk and detect wake word.

        Buffers small chunks until >= 1280 samples are available,
        then runs prediction on the accumulated audio.

        Args:
            audio: Float32 audio samples, typically 16kHz mono.

        Returns:
            WakeWordResult with detection status and confidence.
        """
        if self._model is None:
            return WakeWordResult(detected=False, word=None, confidence=0.0)

        # Buffer small chunks to meet minimum
        self._buffer.append(audio)
        self._buffer_len += len(audio)

        if self._buffer_len < self._MIN_SAMPLES:
            return WakeWordResult(detected=False, word=None, confidence=0.0)

        # Concatenate and process
        combined = np.concatenate(self._buffer)
        self._buffer.clear()
        self._buffer_len = 0

        audio_int16 = (combined * 32767).astype(np.int16)
        prediction = self._model.predict(audio_int16)  # type: ignore[union-attr]

        # Debug: log top score every ~3 seconds (≈37 calls at 80ms)
        self._debug_counter += 1
        if self._debug_counter >= 37:
            self._debug_counter = 0
            top = max(prediction.items(), key=lambda x: x[1]) if prediction else ("?", 0)
            if top[1] > 0.01:
                logger.debug("Wake word scores: top=%s (%.3f)", top[0], top[1])

        for model_name, score in prediction.items():
            if score >= self.threshold:
                logger.info("Wake word detected: %s (score=%.2f)", model_name, score)
                return WakeWordResult(detected=True, word=model_name, confidence=float(score))

        return WakeWordResult(detected=False, word=None, confidence=0.0)

    def reset(self) -> None:
        """Reset internal model state between utterances."""
        if self._model is not None and hasattr(self._model, "reset"):
            self._model.reset()  # type: ignore[union-attr]
