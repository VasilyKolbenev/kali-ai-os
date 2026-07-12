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


#: Multi-word YouTube-style hallucinations Whisper emits on silence/noise.
#: Matched anchored (text equals / starts with / ends with), never as an
#: arbitrary substring, so real commands are never blanked.
_HALLUCINATION_PHRASES: tuple[str, ...] = (
    "субтитры сделал",
    "субтитры делал",
    "субтитры создавал",
    "а на этом у меня всё",
    "спасибо за просмотр",
)

#: Single-word YouTube-credit needles. Whisper emits these standalone on
#: silence; they're common Russian words inside real sentences, so they only
#: count as a hallucination when they ARE the whole utterance.
_HALLUCINATION_WORDS: frozenset[str] = frozenset({"редактор", "корректор"})


def _is_hallucination(text: str) -> bool:
    """Return True if ``text`` is a known Whisper silence-hallucination.

    Uses anchored matching (equality, prefix, or suffix for phrases; whole-text
    equality for single-word needles) instead of substring containment so valid
    utterances that merely contain a common word are kept.

    Args:
        text: The transcribed text to classify.

    Returns:
        True if the text should be dropped as a hallucination.
    """
    lowered = text.strip().lower().rstrip(".!?,")
    if not lowered:
        return False
    if lowered in _HALLUCINATION_WORDS:
        return True
    return any(
        lowered == phrase or lowered.startswith(phrase) or lowered.endswith(phrase)
        for phrase in _HALLUCINATION_PHRASES
    )


class SpeechToText:
    """Transcribes audio to text using faster-whisper.

    Model is lazy-loaded. Without model, returns empty results.
    """

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        # KALI_STT_MODEL overrides the configured size without a rebuild — lets
        # us A/B "small" vs "medium" (more accurate, slower) on the same build.
        import os
        self.model_size = os.environ.get("KALI_STT_MODEL", model_size)
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
        hf_cache = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", ".hf_cache",
        ))
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
        # beam 2 ≈ beam 5 quality on short RU commands at a fraction of the
        # decode time (latency sprint 2026-07-12); the quality-gate judge pins
        # KALI_STT_BEAM=5 so experiments never degrade the judge itself.
        import os as _os
        segments, info = self._model.transcribe(  # type: ignore[union-attr]
            audio,
            beam_size=int(_os.environ.get("KALI_STT_BEAM", "2")),
            language="ru",
            vad_filter=True,
            # Lower threshold + shorter min-silence so quiet/short Russian
            # words at phrase edges aren't clipped by the internal VAD (the
            # "many words missed" complaint). Pipeline-level VAD already
            # bounds the utterance, so this filter only trims dead air.
            vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 300},
            # Bias decoding toward the assistant's domain vocabulary so names
            # and terms stop getting mangled.
            initial_prompt=(
                "Разговор с голосовым ассистентом Джарвис. Темы: напоминания, "
                "задачи, календарь, погода, новости, курс доллара и евро, "
                "биткоин, Telegram, почта, заметки."
            ),
            condition_on_previous_text=False,
        )
        text_parts = [segment.text.strip() for segment in segments]
        text = " ".join(text_parts).strip()

        # Drop common Whisper hallucinations from silence/noise. Match ANCHORED,
        # not arbitrary substrings: a bare `in` check blanked valid commands that
        # merely contained a common word (e.g. «напомни позвонить редактору» was
        # killed by the 'редактор' needle). Multi-word YouTube-credit phrases are
        # matched as prefix/suffix; the single-word credit needles
        # ('редактор'/'корректор') only count when the whole utterance is just
        # that word, never inside a real sentence.
        if _is_hallucination(text):
            text = ""
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info("STT: '%s' (lang=%s, %.0fms)", text, info.language, elapsed_ms)
        return STTResult(
            text=text,
            language=info.language,
            confidence=info.language_probability,
            duration_ms=elapsed_ms,
        )
