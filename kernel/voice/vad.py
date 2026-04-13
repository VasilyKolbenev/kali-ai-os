"""Voice Activity Detection using Silero VAD with energy-based fallback."""

import logging
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class VADResult:
    """Result of voice activity detection."""

    is_speech: bool
    confidence: float


class VoiceActivityDetector:
    """Detects speech in audio chunks.

    Uses Silero VAD when available, falls back to energy-based detection.
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._model: object | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the Silero VAD model."""
        try:
            import torch

            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            self._model = model
            self._loaded = True
            logger.info("Silero VAD model loaded")
        except Exception:
            logger.warning("Failed to load Silero VAD, using energy-based fallback")
            self._loaded = False

    def process(self, audio: np.ndarray, sample_rate: int = 16000) -> VADResult:
        if self._model is not None:
            return self._process_silero(audio, sample_rate)
        return self._process_energy(audio)

    def _process_silero(self, audio: np.ndarray, sample_rate: int) -> VADResult:
        import torch

        tensor = torch.from_numpy(audio)
        confidence = float(self._model(tensor, sample_rate))  # type: ignore[operator]
        return VADResult(is_speech=confidence >= self.threshold, confidence=confidence)

    def _process_energy(self, audio: np.ndarray) -> VADResult:
        rms = float(np.sqrt(np.mean(audio**2)))
        energy_threshold = 0.01
        confidence = min(rms / 0.1, 1.0)
        return VADResult(is_speech=rms > energy_threshold, confidence=confidence)

    def reset(self) -> None:
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()  # type: ignore[union-attr]
