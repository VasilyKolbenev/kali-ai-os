from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from kernel.builder.flow import BuilderFlow
from kernel.builder.intent_classifier import IntentResult
from kernel.builder.session_store import SessionStore


def _mock_intent(type_: str = "skill", template: str = "reminder") -> IntentResult:
    return IntentResult(type=type_, template=template, confidence=0.9, reason="mocked")


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BuilderFlow:
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: _mock_intent(),
    )
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    return BuilderFlow(
        session_store=SessionStore(),
        agents_dir=tmp_path / "agents",
        skill_executor=executor,
        scheduler=None,
    )


async def test_start_returns_first_question(flow: BuilderFlow) -> None:
    result = flow.start("Напомни пить воду каждые 2 часа")
    assert result["session_id"]
    assert result["question"]
    assert result["total_steps"] >= 1


async def test_answer_progresses_until_complete(flow: BuilderFlow) -> None:
    start = flow.start("Напомни пить воду")
    sid = start["session_id"]

    total = start["total_steps"]
    for i in range(total):
        result = flow.answer(sid, f"ответ-{i}")
        if result["done"]:
            assert i == total - 1
            assert result["preview"]["name"]
            return
    pytest.fail("Wizard didn't complete after all answers")


async def test_deploy_creates_skill(flow: BuilderFlow) -> None:
    start = flow.start("Напомни пить воду")
    sid = start["session_id"]
    for _ in range(start["total_steps"]):
        flow.answer(sid, "каждые 2 часа")
    result = await flow.deploy(sid)
    assert result["status"] == "deployed"


async def test_cancel_removes_session(flow: BuilderFlow) -> None:
    start = flow.start("Напомни")
    sid = start["session_id"]
    flow.cancel(sid)
    with pytest.raises(Exception):
        flow.answer(sid, "x")


async def test_start_raises_for_agent_intent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pilot scope: agent generation path is blocked."""
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: IntentResult(type="agent", template=None, confidence=0.9, reason="mocked"),
    )
    executor = MagicMock()
    flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=tmp_path / "agents",
        skill_executor=executor,
    )
    with pytest.raises(ValueError, match="Agent generation out of pilot scope"):
        flow.start("сделай агента для парсинга криптобирж")


async def test_deploy_without_complete_wizard_raises(flow: BuilderFlow) -> None:
    """Deploy before wizard is done must fail clearly."""
    start = flow.start("Напомни")
    sid = start["session_id"]
    # Don't feed any answers — spec stays None
    with pytest.raises(ValueError, match="wizard not complete"):
        await flow.deploy(sid)
