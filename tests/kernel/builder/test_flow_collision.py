"""Tests for Cluster C8 finding 1 — voice-builder slug collision must never
overwrite or (on rollback) delete a pre-existing agent (data loss P0)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from kernel.builder.flow import BuilderFlow
from kernel.builder.intent_classifier import IntentResult
from kernel.builder.session_store import SessionStore


def _mock_intent() -> IntentResult:
    return IntentResult(type="skill", template="reminder", confidence=0.9, reason="mocked")


def _run_build(flow: BuilderFlow, request: str) -> dict:
    start = flow.start(request)
    sid = start["session_id"]
    for _ in range(start["total_steps"]):
        flow.answer(sid, "каждые 2 часа")
    import asyncio

    return asyncio.get_event_loop().run_until_complete(flow.deploy(sid))


async def test_collision_does_not_overwrite_or_delete_prior_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Build 'foo'; then build a second slug-'foo' whose load_skill is forced to
    fail. The FIRST skill's dir + manifest must still exist afterward, and the
    second deploy must not have overwritten the first's manifest."""
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent", lambda req: _mock_intent()
    )
    agents_dir = tmp_path / "agents"

    # --- first build succeeds ---
    executor1 = MagicMock()
    executor1.load_skill = MagicMock()
    executor1.get_skill_info = MagicMock(return_value={"config": {}})
    flow1 = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=agents_dir,
        skill_executor=executor1,
        scheduler=None,
    )
    start = flow1.start("foo")
    sid = start["session_id"]
    for _ in range(start["total_steps"]):
        flow1.answer(sid, "каждые 2 часа")
    result1 = await flow1.deploy(sid)
    assert result1["status"] == "deployed"

    first_dir = agents_dir / "foo"
    assert first_dir.exists()
    first_manifest_before = (first_dir / "manifest.yaml").read_text(encoding="utf-8")

    # --- second build, same slug, load forced to fail (triggers rollback) ---
    executor2 = MagicMock()
    executor2.load_skill = MagicMock(side_effect=RuntimeError("boom"))
    flow2 = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=agents_dir,
        skill_executor=executor2,
        scheduler=None,
    )
    start2 = flow2.start("foo")
    sid2 = start2["session_id"]
    for _ in range(start2["total_steps"]):
        flow2.answer(sid2, "каждые 2 часа")
    result2 = await flow2.deploy(sid2)

    # Second deploy fails (load failed) ...
    assert result2["status"] == "error"
    # ... but the FIRST agent's dir + manifest are untouched (no data loss).
    assert first_dir.exists()
    assert (first_dir / "manifest.yaml").exists()
    assert (
        first_dir / "manifest.yaml"
    ).read_text(encoding="utf-8") == first_manifest_before
