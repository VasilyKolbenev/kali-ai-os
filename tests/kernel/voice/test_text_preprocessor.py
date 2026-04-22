"""Tests for Russian text preprocessing for F5-TTS."""

from __future__ import annotations

import pytest

from kernel.voice import text_preprocessor as tp


class TestPunctuation:
    def test_em_dash_to_comma(self) -> None:
        assert tp._normalize_punctuation("привет — мир") == "привет, мир."

    def test_en_dash_to_comma(self) -> None:
        assert tp._normalize_punctuation("привет – мир") == "привет, мир."

    def test_hyphen_dash_to_comma(self) -> None:
        assert tp._normalize_punctuation("привет - мир") == "привет, мир."

    def test_multiple_spaces_collapse(self) -> None:
        assert tp._normalize_punctuation("a  b   c") == "a b c."

    def test_adds_trailing_period(self) -> None:
        assert tp._normalize_punctuation("привет") == "привет."

    def test_preserves_trailing_question(self) -> None:
        assert tp._normalize_punctuation("привет?") == "привет?"

    def test_preserves_trailing_exclaim(self) -> None:
        assert tp._normalize_punctuation("привет!") == "привет!"


class TestAbbreviations:
    def test_te_expansion(self) -> None:
        assert "то есть" in tp._expand_abbreviations("т.е. хорошо")

    def test_td_expansion(self) -> None:
        assert "так далее" in tp._expand_abbreviations("и т.д.")

    def test_tp_expansion(self) -> None:
        assert "тому подобное" in tp._expand_abbreviations("и т.п.")

    def test_case_insensitive(self) -> None:
        assert "то есть" in tp._expand_abbreviations("Т.Е. хорошо")

    def test_preserves_non_abbr(self) -> None:
        assert tp._expand_abbreviations("привет") == "привет"


class TestIntToWords:
    def test_zero(self) -> None:
        assert tp._int_to_words(0) == "ноль"

    def test_one(self) -> None:
        assert tp._int_to_words(1) == "один"

    def test_teen(self) -> None:
        assert tp._int_to_words(19) == "девятнадцать"

    def test_twenty(self) -> None:
        assert tp._int_to_words(20) == "двадцать"

    def test_twenty_one(self) -> None:
        assert tp._int_to_words(21) == "двадцать один"

    def test_ninety_nine(self) -> None:
        assert tp._int_to_words(99) == "девяносто девять"

    def test_hundred(self) -> None:
        assert tp._int_to_words(100) == "сто"

    def test_one_twenty_three(self) -> None:
        assert tp._int_to_words(123) == "сто двадцать три"

    def test_max(self) -> None:
        assert tp._int_to_words(999) == "девятьсот девяносто девять"

    def test_negative(self) -> None:
        assert tp._int_to_words(-5) == "минус пять"

    def test_overflow_returns_digits(self) -> None:
        assert tp._int_to_words(1000) == "1000"


class TestExpandNumbers:
    def test_single_digit_in_sentence(self) -> None:
        assert tp._expand_numbers("2 часа") == "два часа"

    def test_two_digits_in_sentence(self) -> None:
        assert tp._expand_numbers("25 минут") == "двадцать пять минут"

    def test_hundred(self) -> None:
        assert tp._expand_numbers("100 грамм") == "сто грамм"

    def test_leaves_year_alone(self) -> None:
        """2026 stays as-is (TTS handles years better than spelled-out)."""
        assert tp._expand_numbers("2026 год") == "2026 год"

    def test_mixed_numbers(self) -> None:
        """Small spelled out, large kept as digits."""
        assert tp._expand_numbers("5 раз в 2026") == "пять раз в 2026"


class TestPreprocessEndToEnd:
    def test_empty_string(self) -> None:
        assert tp.preprocess("") == ""

    def test_whitespace_only_passthrough(self) -> None:
        assert tp.preprocess("   ") == "   "

    def test_combined_without_accenter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify punctuation + numbers applied even when accenter is unavailable."""
        tp._get_accenter.cache_clear()
        monkeypatch.setattr(tp, "_get_accenter", lambda: None)
        result = tp.preprocess("привет — мир, 2 часа")
        assert "два часа" in result
        assert "," in result
        assert result.endswith(".")

    def test_opt_out_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KALI_TTS_ACCENT=0 disables the accenter entirely."""
        tp._get_accenter.cache_clear()
        monkeypatch.setenv("KALI_TTS_ACCENT", "0")
        assert tp._get_accenter() is None

    def test_preprocess_failure_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If preprocessing raises, original input is returned unchanged."""
        def _boom(_: str) -> str:
            raise RuntimeError("synthetic")

        monkeypatch.setattr(tp, "_normalize_punctuation", _boom)
        raw = "некий текст"
        assert tp.preprocess(raw) == raw
