"""Tests for voice wizard."""

import pytest

from kernel.builder.intent_classifier import IntentResult
from kernel.builder.wizard import WizardSession, create_wizard, _slugify


class TestWizard:
    def test_create_skill_wizard(self):
        intent = IntentResult(type="skill", template="tracker", confidence=0.9, reason="test")
        wizard = create_wizard("track water", intent)
        assert len(wizard.questions) > 0
        assert not wizard.is_complete

    def test_answer_advances_step(self):
        intent = IntentResult(type="skill", template="tracker", confidence=0.9, reason="test")
        wizard = create_wizard("track water", intent)
        next_q = wizard.answer("2000 ml")
        assert len(wizard.answers) == 1
        if next_q:
            assert wizard._step == 1

    def test_complete_after_all_answers(self):
        intent = IntentResult(type="skill", template="reminder", confidence=0.9, reason="test")
        wizard = create_wizard("remind water", intent)
        for _ in range(len(wizard.questions)):
            wizard.answer("test answer")
        assert wizard.is_complete

    def test_build_spec_returns_dict(self):
        intent = IntentResult(type="skill", template="tracker", confidence=0.9, reason="test")
        wizard = create_wizard("track water", intent)
        for _ in range(len(wizard.questions)):
            wizard.answer("test")
        spec = wizard.build_spec()
        assert "name" in spec
        assert "type" in spec
        assert spec["type"] == "skill"

    def test_agent_wizard_has_questions(self):
        intent = IntentResult(type="agent", template=None, confidence=0.8, reason="test")
        wizard = create_wizard("parse aviasales", intent)
        assert len(wizard.questions) >= 2


class TestSlugify:
    def test_basic(self):
        assert _slugify("Track Water Intake") == "track-water-intake"

    def test_special_chars_removed(self):
        result = _slugify("Трекер воды!")
        assert "!" not in result

    def test_long_truncated(self):
        result = _slugify("a" * 100)
        assert len(result) <= 40

    def test_empty_string(self):
        result = _slugify("")
        assert result == ""
