"""Pure metric functions for the on-device TTS eval harness.

No model or audio dependency — these operate on strings and timings, so they
are unit-testable in isolation (see test_metrics.py). The model-dependent glue
(synthesis, STT transcription) lives in run_eval.py.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Combining acute (U+0301), ASCII '+', and the typographic stress marks RUAccent
# / our pipeline may emit. Stripped before comparison so stress annotation never
# counts as a transcription error.
_STRESS_CHARS = "+́́`´"
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_ru(text: str) -> str:
    """Normalize Russian text for fair WER/CER comparison.

    Lowercases, folds ``ё`` → ``е``, removes stress marks and punctuation, and
    collapses whitespace. Digits/word-chars are kept (number normalization to
    spoken form is the eval set's job via a ``spoken`` reference, not this fn).

    Args:
        text: Raw reference or hypothesis text.

    Returns:
        A normalized, comparison-ready string.
    """
    lowered = text.lower().replace("ё", "е")
    stripped = lowered.translate({ord(c): None for c in _STRESS_CHARS})
    no_punct = _PUNCT_RE.sub(" ", stripped)
    return _WS_RE.sub(" ", no_punct).strip()


def _levenshtein(a: Sequence[object], b: Sequence[object]) -> int:
    """Edit distance between two sequences (tokens or characters).

    Args:
        a: Reference sequence.
        b: Hypothesis sequence.

    Returns:
        Minimum single-element insert/delete/substitute operations.
    """
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word error rate after Russian normalization.

    Args:
        reference: Expected spoken text.
        hypothesis: STT transcription of the synthesized audio.

    Returns:
        WER in [0, ∞): edits / reference-word-count. 0.0 means identical; an
        empty reference returns 0.0 if the hypothesis is also empty, else 1.0.
    """
    ref_words = normalize_ru(reference).split()
    hyp_words = normalize_ru(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _levenshtein(ref_words, hyp_words) / len(ref_words)


def char_error_rate(reference: str, hypothesis: str) -> float:
    """Character error rate after Russian normalization (whitespace ignored).

    Args:
        reference: Expected spoken text.
        hypothesis: STT transcription of the synthesized audio.

    Returns:
        CER in [0, ∞): char edits / reference-char-count.
    """
    ref = normalize_ru(reference).replace(" ", "")
    hyp = normalize_ru(hypothesis).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def real_time_factor(synth_seconds: float, audio_seconds: float) -> float:
    """Real-time factor — the on-device speed gate.

    Args:
        synth_seconds: Wall-clock time spent synthesizing.
        audio_seconds: Duration of the produced audio.

    Returns:
        RTF = synth_seconds / audio_seconds. < 1.0 means faster-than-real-time
        (usable for streaming); the on-device target. Raises ``ValueError`` if
        ``audio_seconds`` is not positive.
    """
    if audio_seconds <= 0:
        raise ValueError("audio_seconds must be positive")
    return synth_seconds / audio_seconds
