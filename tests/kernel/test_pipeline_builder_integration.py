"""Tests for builder trigger detection in voice pipeline."""

from __future__ import annotations

import pytest

from kernel.voice.pipeline import _detect_builder_trigger


@pytest.mark.parametrize("text,expected", [
    ("Создай агента чтобы напоминал пить воду", True),
    ("Сделай агента для отслеживания курса биткоина", True),
    ("Сделай скилл напоминалку", True),
    ("Создай скилл для дневника настроения", True),
    ("Какая погода?", False),
    ("Открой калькулятор", False),
    ("", False),
])
def test_detect_builder_trigger(text: str, expected: bool) -> None:
    assert _detect_builder_trigger(text) == expected
