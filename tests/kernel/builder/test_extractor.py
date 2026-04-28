"""Tests for the LLM-driven /builder/extract logic.

The actual LLM call is mocked — we test the wiring (template
validation, BuilderSession mutation contract, fallback behaviour).
"""
from __future__ import annotations

from typing import Any

import pytest

from kernel.builder import extractor
from kernel.builder.intent_classifier import IntentResult
from kernel.builder.session_store import SessionStore


def test_system_prompt_lists_all_template_keys() -> None:
    """Verbatim prompt mentions every template + every config key the
    helper recognises. Drift in either direction breaks A4 fast-path.
    """
    p = extractor.LLM_SYSTEM_PROMPT
    for tmpl in ("tracker", "reminder", "monitor", "notifier", "logger"):
        assert tmpl in p
    for key in (
        "interval", "goal", "notify_channel", "time_window",
        "target", "trigger", "categories",
    ):
        assert key in p
    assert "STRICT JSON" in p


def _stub_llm(template: str, name_hint: str, extracted: dict[str, str]):
    """Return a function suitable for monkeypatching extractor._call_llm."""
    def _fake(_request: str) -> dict[str, Any]:
        return {
            "type": "skill",
            "template": template,
            "name_hint": name_hint,
            "extracted": extracted,
            "confidence": 0.9,
        }
    return _fake


def test_extract_complete_returns_full_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three tracker fields extracted → complete=True, no wizard turn needed."""
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("tracker", "treker-vody", {
            "interval": "2 часа",
            "goal": "2 литра",
            "notify_channel": "чат",
        }),
    )
    store = SessionStore()
    result = extractor.extract_spec(
        request="трекер воды два литра каждые два часа в чат",
        session_store=store,
    )

    assert result["complete"] is True
    assert result["session_id"] in store._sessions
    spec = result["spec"]
    assert spec["template"] == "tracker"
    assert spec["name"] == "treker-vody"
    assert spec["config"]["interval"] == "2 часа"
    assert spec["config"]["goal"] == "2 литра"
    assert spec["config"]["notify_channel"] == "чат"


def test_extract_partial_pre_populates_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two of three tracker fields extracted → complete=False, wizard
    resumes at the first un-extracted question.
    """
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("tracker", "treker-vody", {
            "interval": "2 часа",
            "notify_channel": "чат",
        }),
    )
    store = SessionStore()
    result = extractor.extract_spec(
        request="трекер воды каждые два часа в чат",
        session_store=store,
    )

    assert result["complete"] is False
    sid = result["session_id"]
    session = store.get(sid)

    # Tracker question order: ["Какая дневная цель?", "Как часто напоминать?",
    # "Куда отправлять уведомления — голосом или в телеграм?"]
    # Goal is question[0] → missing → step=0 → answers=[]
    assert session.step == 0
    assert session.answers == []
    assert result["next_question"] == "Какая дневная цель?"
    assert result["partial_spec"]["template"] == "tracker"


def test_extract_partial_fills_in_question_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Goal extracted but interval missing → wizard resumes at interval (q1),
    answers pre-populated for goal (q0) only.
    """
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("tracker", "treker-vody", {
            "goal": "2 литра",
            "notify_channel": "чат",
        }),
    )
    store = SessionStore()
    result = extractor.extract_spec(
        request="трекер 2 литра в чат",
        session_store=store,
    )

    assert result["complete"] is False
    sid = result["session_id"]
    session = store.get(sid)
    assert session.step == 1
    assert session.answers == ["2 литра"]
    assert result["next_question"] == "Как часто напоминать?"


def test_extract_invalid_template_falls_back_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM picks an unknown template → fallback creates a session via
    classify_intent + create_wizard like /builder/start would.
    """
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("nonsense", "x", {}),
    )
    monkeypatch.setattr(
        "kernel.builder.extractor.classify_intent",
        lambda r: IntentResult(type="skill", template="reminder", confidence=0.9, reason="mock"),
    )
    store = SessionStore()
    result = extractor.extract_spec(request="напомни кушать", session_store=store)

    assert result["complete"] is False
    session = store.get(result["session_id"])
    assert session.template == "reminder"
    assert session.step == 0
    assert session.answers == []


def test_extract_llm_unavailable_falls_back_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """No LLM provider → fallback to /builder/start equivalent."""
    monkeypatch.setattr(extractor, "_call_llm", lambda r: None)
    monkeypatch.setattr(
        "kernel.builder.extractor.classify_intent",
        lambda r: IntentResult(type="skill", template="logger", confidence=0.9, reason="mock"),
    )
    store = SessionStore()
    result = extractor.extract_spec(request="дневник настроения", session_store=store)

    assert result["complete"] is False
    assert result["next_question"] == "Какие события записывать?"
