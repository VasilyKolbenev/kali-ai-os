"""Keystone core-loop e2e: voice "create → works → share" with REAL components.

Drives the real builder HTTP flow (``/builder/start`` → ``/builder/answer``×N →
``/builder/deploy``) against a **real** :class:`~kernel.skill_executor.SkillExecutor`
and a **real** :class:`~kernel.plugin_registry.PluginRegistry`, then proves the
deployed skill is genuinely:

    (a) interval-parsed   — ``reminders.interval_hours`` written to skill.yaml,
    (b) cron-registered   — scheduler got ``register_cron(..., topic=skill.{name}.trigger)``,
    (c) LLM-callable       — the real registry advertises ``{name}__check`` in get_all_tools(),
    (d) dispatchable       — the real executor runs the tool to a non-error result.

Unlike ``test_builder_voice_e2e.py`` (MagicMock executor, files-on-disk only),
this exercises the actual deploy → register_dir → execute path end to end. It is
ML-free (template skills run in-process; no torch/F5/whisper).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore
from kernel.event_bus import EventBus
from kernel.llm_router import LLMResponse, ToolCall
from kernel.main import create_app
from kernel.models import ScheduleConfig
from kernel.plugin_registry import PluginRegistry
from kernel.scheduler import Scheduler
from kernel.skill_executor import SkillExecutor
from kernel.tool_dispatch import execute_tool_call


class _MockIntent:
    """Stand-in for intent_classifier output — only the reminder template path."""

    def __init__(self, type_: str = "skill", template: str = "reminder") -> None:
        self.type = type_
        self.template = template
        self.confidence = 0.9
        self.reason = "mocked"


class _StubRouter:
    """Minimal LLMRouter stand-in for the cosmetic second-pass only.

    ``execute_tool_call`` runs the real tool through the real executor, then asks
    the router to phrase the raw result naturally for the user. That phrasing
    pass is the ONLY thing this stub replaces — it avoids a live LLM call while
    the real executor/registry still perform the actual dispatch. It is NOT one
    of the components under test (executor, registry, deployer, generator,
    tool_dispatch are all real).
    """

    async def route(self, request: Any) -> LLMResponse:
        return LLMResponse(
            text="ok", tool_calls=None, provider_used="stub", latency_ms=0
        )


@pytest.mark.asyncio
async def test_core_loop_build_deploy_cron_callable_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full loop with real executor + registry: build → deploy → cron → callable → dispatch."""
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: _MockIntent(),
    )

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # REAL components — mirrors create_app wiring on tmp dirs.
    skill_executor = SkillExecutor(data_dir=data_dir)
    plugin_registry = PluginRegistry(agents_dir=agents_dir)
    scheduler = Scheduler(EventBus(), ScheduleConfig())

    # Spy on the scheduler's cron registration (record the call; do NOT run a
    # real wall-clock cron). The scheduler itself is real otherwise.
    cron_calls: list[dict[str, Any]] = []
    real_register_cron = scheduler.register_cron

    def _spy_register_cron(name: str, cron_expr: str, topic: str | None = None) -> None:
        cron_calls.append({"name": name, "cron_expr": cron_expr, "topic": topic})
        real_register_cron(name, cron_expr, topic=topic)

    monkeypatch.setattr(scheduler, "register_cron", _spy_register_cron)

    app = create_app()
    app.state.skill_executor = skill_executor
    app.state.plugin_registry = plugin_registry
    app.state.scheduler = scheduler
    app.state.agent_runtime = None  # not needed for a skill-protocol dispatch
    app.state.builder_flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=agents_dir,
        skill_executor=skill_executor,
        scheduler=scheduler,
        plugin_registry=plugin_registry,
    )

    # --- Drive the real builder flow over HTTP ---------------------------------
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/builder/start",
            json={"request": "напоминай пить воду каждые 2 часа"},
        )
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        total = r.json()["total_steps"]

        answers = ["каждые 2 часа", "с 9 утра до 10 вечера", "голосом"]
        for i in range(total):
            answer = answers[i] if i < len(answers) else "default"
            r = await c.post(
                "/builder/answer",
                json={"session_id": sid, "answer": answer},
            )
            assert r.status_code == 200, r.text

        r = await c.post("/builder/deploy", json={"session_id": sid})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "deployed", r.json()
        skill_name = r.json()["name"]

    # ===========================================================================
    # (a) interval parsed: skill.yaml carries reminders.interval_hours == 2
    # ===========================================================================
    skill_yaml_path = agents_dir / skill_name / "skill.yaml"
    assert skill_yaml_path.is_file(), f"skill.yaml not written at {skill_yaml_path}"
    skill_cfg = yaml.safe_load(skill_yaml_path.read_text(encoding="utf-8"))
    reminders = skill_cfg["config"].get("reminders")
    assert isinstance(reminders, dict), f"no reminders block: {skill_cfg['config']}"
    assert reminders.get("interval_hours") == 2, (
        f"expected interval_hours=2 from 'каждые 2 часа', got {reminders!r}"
    )

    # ===========================================================================
    # (b) cron registered with topic skill.{name}.trigger
    # ===========================================================================
    assert cron_calls, "scheduler.register_cron was never called"
    cron_call = next((c for c in cron_calls if c["name"] == skill_name), None)
    assert cron_call is not None, f"no cron registered for '{skill_name}': {cron_calls}"
    assert cron_call["topic"] == f"skill.{skill_name}.trigger", cron_call
    # interval_hours=2 → "0 */2 * * *"
    assert "*/2" in cron_call["cron_expr"], cron_call

    # ===========================================================================
    # (c) LLM-callable: the SAME real registry advertises {name}__check
    # ===========================================================================
    tool_names = {
        t["function"]["name"]
        for t in plugin_registry.get_all_tools()
        if "function" in t
    }
    expected_tool = f"{skill_name}__check"  # reminder template's tool is "check"
    assert expected_tool in tool_names, (
        f"{expected_tool} not in LLM palette: {sorted(tool_names)}"
    )

    # ===========================================================================
    # (d) dispatchable: execute_tool_call runs the REAL executor to a real result
    # ===========================================================================
    dispatched = await execute_tool_call(
        state=app.state,
        router=_StubRouter(),  # cosmetic 2nd-pass only; see _StubRouter docstring
        call=ToolCall(name=expected_tool, arguments={}),
        context=[],
        user_text="проверь напоминание",
    )
    assert dispatched is not None, "execute_tool_call returned None (tool not routed)"
    _text, raw_result, source = dispatched
    assert isinstance(raw_result, dict), f"non-dict result: {raw_result!r}"
    assert "error" not in raw_result, f"tool raised an error: {raw_result!r}"
    # The reminder 'check' action returns a should_fire decision, never "not found".
    assert "should_fire" in raw_result, f"unexpected check result: {raw_result!r}"
    assert source == f"agent-{skill_name}"
