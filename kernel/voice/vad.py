"""Voice Activity Detection using Silero VAD with energy-based fallback."""

import logging
from dataclasses import dataclass
from pathlib import Path

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
        """Load the Silero VAD model.

        On Windows the default torch hub cache can become locked by another
        process. We pre-check cache readability and redirect to a temp dir
        when needed, then fall back to energy-based detection on failure.
        """
        self._ensure_hub_cache()
        try:
            import torch

            # Skip GitHub fork-check that crashes on rate-limit (PyTorch bug)
            torch.hub._validate_not_a_forked_repo = lambda a, b, c: True
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            self._model = model
            self._loaded = True
            logger.info("Silero VAD model loaded")
        except Exception as e:
            logger.warning("Failed to load Silero VAD: %s, using energy fallback", e)
            self._loaded = False

    @staticmethod
    def _ensure_hub_cache() -> None:
        """Redirect torch hub cache if the default dir is inaccessible.

        Checks both directory listing AND file read access, since Windows
        can lock individual files while the directory remains listable.
        """
        import os
        import tempfile

        import torch

        default_dir = torch.hub.get_dir()
        vad_cache = Path(default_dir) / "snakers4_silero-vad_master"

        needs_redirect = False
        if vad_cache.exists():
            try:
                os.listdir(vad_cache)
                # Also check file-level access (hubconf.py is required by torch.hub)
                hubconf = vad_cache / "hubconf.py"
                if hubconf.exists():
                    hubconf.read_text(encoding="utf-8")
            except (PermissionError, OSError):
                needs_redirect = True
        # Also redirect if default cache had permission issues previously
        if not needs_redirect:
            return

        logger.warning(
            "Silero VAD cache at %s is locked, redirecting to temp dir",
            vad_cache,
        )
        tmp_hub = Path(tempfile.gettempdir()) / "kali_torch_hub"
        tmp_hub.mkdir(exist_ok=True)
        torch.hub.set_dir(str(tmp_hub))

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
