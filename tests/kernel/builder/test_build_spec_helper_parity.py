"""Both _build_spec implementations must produce the same config dict
when fed the same questions+answers. Locks the helper-refactor.
"""
from __future__ import annotations

from kernel.builder.flow import BuilderFlow
from kernel.builder.intent_classifier import IntentResult
from kernel.builder.session_store import BuilderSession
from kernel.builder.wizard import WizardSession


def _make_intent() -> IntentResult:
    return IntentResult(type="skill", template="tracker", confidence=0.9, reason="test")


def test_helper_drives_config_keys_consistently() -> None:
    questions = [
        "Какая дневная цель?",
        "Как часто напоминать?",
        "Куда отправлять уведомления — голосом или в телеграм?",
    ]
    answers = ["2 литра", "каждые 2 часа", "в чат"]

    # WizardSession path
    ws = WizardSession(request="трекер воды", intent=_make_intent(), questions=questions)
    for a in answers:
        ws.answer(a)
    spec_ws = ws.build_spec()

    # BuilderFlow path
    bs = BuilderSession(
        session_id="x",
        request="трекер воды",
        intent_type="skill",
        template="tracker",
        questions=questions,
        answers=answers,
        step=len(answers),
    )
    flow = BuilderFlow.__new__(BuilderFlow)  # bypass __init__ — we only test _build_spec
    spec_flow = flow._build_spec(bs)

    assert spec_ws["config"] == spec_flow["config"]
    assert spec_ws["config"] == {
        "goal": "2 литра",
        "interval": "каждые 2 часа",
        "notify_channel": "в чат",
    }
