"""Unit tests for the pure TTS eval metrics (no model needed)."""

import pytest

from metrics import char_error_rate, normalize_ru, real_time_factor, word_error_rate


def test_normalize_lowercases_and_strips_punct() -> None:
    assert normalize_ru("Готов, сэр!") == "готов сэр"


def test_normalize_folds_yo() -> None:
    assert normalize_ru("Ёлка") == "елка"


def test_normalize_strips_stress_marks() -> None:
    # combining acute U+0301 and ASCII '+' must not count as content
    assert normalize_ru("гото́в") == "готов"
    assert normalize_ru("+20") == "20"


def test_wer_identical_is_zero() -> None:
    assert word_error_rate("привет мир как дела", "привет мир как дела") == 0.0


def test_wer_one_substitution_in_four() -> None:
    assert word_error_rate("привет мир как дела", "привет мир как день") == pytest.approx(0.25)


def test_wer_ignores_case_and_punctuation() -> None:
    assert word_error_rate("Ужин уже готов, сэр.", "ужин уже готов сэр") == 0.0


def test_wer_empty_reference() -> None:
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "что-то") == 1.0


def test_cer_identical_is_zero() -> None:
    assert char_error_rate("готов", "готов") == 0.0


def test_cer_one_char() -> None:
    # "готов" (5 chars) vs "готоф" → 1 substitution / 5
    assert char_error_rate("готов", "готоф") == pytest.approx(0.2)


def test_rtf_basic() -> None:
    assert real_time_factor(0.5, 1.0) == 0.5
    assert real_time_factor(2.0, 1.0) == 2.0  # slower than real-time


def test_rtf_rejects_nonpositive_audio() -> None:
    with pytest.raises(ValueError):
        real_time_factor(1.0, 0.0)
