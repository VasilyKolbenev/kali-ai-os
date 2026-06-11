"""Russian text preprocessing for F5-TTS — stress marks, punctuation, numbers.

Pipeline order (matters):
1. Normalize punctuation — em/en dashes → commas, collapse spaces, trailing dot
2. Expand abbreviations — "т.е." → "то есть", etc.
3. Expand short numbers (0-999) — "2 часа" → "два часа"
4. Apply stress marks via ruaccent — "замок" → "з+амок" (F5 Russian understands "+")

Opt-out: set ``KALI_TTS_ACCENT=0`` to disable accent step (punctuation/numbers
still applied). Failures at any stage fall through to raw input.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_accenter() -> Any | None:
    """Lazy-load RUAccent. Returns None if disabled or unavailable."""
    if os.environ.get("KALI_TTS_ACCENT", "1") == "0":
        logger.info("Accent preprocessor disabled via KALI_TTS_ACCENT=0")
        return None
    try:
        from ruaccent import RUAccent
        acc = RUAccent()
        acc.load(omograph_model_size="turbo", use_dictionary=True)
        logger.info("RUAccent loaded (turbo + dictionary)")
        return acc
    except Exception as exc:
        logger.warning("RUAccent unavailable (%s) — plain text fallback", exc)
        return None


# Common Russian abbreviations TTS engines typically mispronounce
_ABBR_MAP: dict[str, str] = {
    r"\bт\.\s*е\.": "то есть",
    r"\bт\.\s*д\.": "так далее",
    r"\bт\.\s*п\.": "тому подобное",
    r"\bи\s+т\.\s*д\.": "и так далее",
    r"\bи\s+т\.\s*п\.": "и тому подобное",
    r"\bдр\.": "другие",
    r"\bсм\.": "смотри",
}


def _normalize_punctuation(text: str) -> str:
    """Normalize punctuation for better TTS prosody."""
    # Em/en dashes → commas (softer pause, F5 handles commas better)
    text = re.sub(r"\s*[\u2014\u2013]\s*", ", ", text)
    # Hyphen surrounded by spaces (used as dash) → comma
    text = re.sub(r"\s+-\s+", ", ", text)
    # Multiple spaces → single
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    # Ensure sentence ends with terminal punctuation (prevents abrupt cutoff)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _expand_abbreviations(text: str) -> str:
    """Expand common RU abbreviations that TTS mispronounces."""
    for pattern, replacement in _ABBR_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _decap_sentence_starts(text: str) -> str:
    """Lowercase ONLY grammatical capitals (sentence-initial letters).

    The accent dictionary is case-sensitive and reads a capitalized
    sentence-start as a proper name: «Готов, сэр» got marked as the surname
    Г+отов (гОтов) while «готов» marks correctly as гот+ов. Sentence-initial
    capitalization carries no meaning for speech, and TTS itself is
    case-insensitive, so the lowercased text ships to the engine as-is.
    Mid-sentence capitals (real proper names: Самара, Вася) are untouched.
    """
    return re.sub(
        r"(^|[.!?…]\s+)([А-ЯЁ])",
        lambda m: m.group(1) + m.group(2).lower(),
        text,
    )


# Russian number words (0-999)
_ONES = [
    "", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
]
_TENS = [
    "", "", "двадцать", "тридцать", "сорок", "пятьдесят",
    "шестьдесят", "семьдесят", "восемьдесят", "девяносто",
]
_HUNDREDS = [
    "", "сто", "двести", "триста", "четыреста", "пятьсот",
    "шестьсот", "семьсот", "восемьсот", "девятьсот",
]


def _int_to_words(n: int) -> str:
    """Convert 0-999 to Russian words (masculine form).

    Years and numbers above 999 are not handled — F5 reads multi-digit numbers
    reasonably, and spelling out "2026" as full Russian is rarely needed.
    """
    if n < 0:
        return "минус " + _int_to_words(-n)
    if n == 0:
        return "ноль"
    if n > 999:
        return str(n)
    parts: list[str] = []
    h, rem = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if rem < 20:
        if rem:
            parts.append(_ONES[rem])
    else:
        t, o = divmod(rem, 10)
        parts.append(_TENS[t])
        if o:
            parts.append(_ONES[o])
    return " ".join(parts)


def _expand_numbers(text: str) -> str:
    """Replace standalone integers (0-999) with Russian words.

    Leaves larger numbers (years, codes) as digits — F5 handles them
    reasonably well and expanding "2026" would be "две тысячи двадцать шесть"
    which is rarely what's wanted in a butler tone.
    """
    def repl(m: re.Match) -> str:
        num = int(m.group(0))
        if num > 999:
            return m.group(0)
        return _int_to_words(num)
    return re.sub(r"\b\d+\b", repl, text)


def preprocess(text: str) -> str:
    """Apply all Russian text preprocessing stages in sequence.

    Args:
        text: Raw input text (RU or RU/EN mix).

    Returns:
        Preprocessed text with normalized punctuation, expanded abbreviations,
        spelled-out short numbers, and stress marks (if ruaccent available).
        On any failure, returns the original input.
    """
    if not text or not text.strip():
        return text

    original = text
    try:
        text = _normalize_punctuation(text)
        text = _expand_abbreviations(text)
        text = _expand_numbers(text)
        accenter = _get_accenter()
        if accenter is not None:
            try:
                text = accenter.process_all(_decap_sentence_starts(text))
            except Exception:
                logger.debug("RUAccent failed mid-text, using pre-accent input")
        return text
    except Exception as exc:
        logger.warning("Preprocessing failed (%s) — returning raw input", exc)
        return original
