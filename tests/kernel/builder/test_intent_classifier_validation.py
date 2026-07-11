"""Tests for Cluster C8 finding 2 — the LLM intent classifier must validate the
returned template and tolerate a non-numeric confidence, instead of returning an
invalid template or crashing on float() and breaking the wizard/deploy."""

from __future__ import annotations

import pytest

from kernel.builder.intent_classifier import classify_intent
from kernel.builder.wizard import create_wizard

_VALID_TEMPLATES = {"tracker", "reminder", "monitor", "notifier", "logger"}


def _stub_llm(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    """Force the LLM path: a provider is detected and _call_llm returns payload."""
    import json

    import kernel.builder.agent_generator as ag

    monkeypatch.setattr(ag, "_detect_provider", lambda: ("anthropic", "claude-x"))
    monkeypatch.setattr(
        ag, "_call_llm", lambda provider, model, system, user: json.dumps(payload)
    )


def test_invalid_template_and_confidence_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returns a bogus template 'counter' and confidence 'high' (non-numeric).
    classify_intent must not raise and must yield a valid template (or regex
    fallback)."""
    _stub_llm(
        monkeypatch,
        {"type": "skill", "template": "counter", "confidence": "high"},
    )
    result = classify_intent("считай стаканы воды")
    assert result.type == "skill"
    # Either coerced to a valid template, or None (regex fallback path).
    assert result.template is None or result.template in _VALID_TEMPLATES
    assert isinstance(result.confidence, float)


def test_create_wizard_yields_questions_after_bad_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm(
        monkeypatch,
        {"type": "skill", "template": "counter", "confidence": "high"},
    )
    result = classify_intent("считай стаканы воды")
    wizard = create_wizard("считай стаканы воды", result)
    assert len(wizard.questions) >= 1


def test_valid_llm_template_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_llm(
        monkeypatch,
        {"type": "skill", "template": "reminder", "confidence": 0.9},
    )
    result = classify_intent("напоминай пить воду")
    assert result.type == "skill"
    assert result.template == "reminder"
    assert result.confidence == pytest.approx(0.9)
