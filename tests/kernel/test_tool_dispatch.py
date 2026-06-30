"""Tests for the shared LLM tool-call dispatch (chat + voice use one path)."""

from unittest.mock import AsyncMock, MagicMock

from kernel.llm_router import LLMResponse, ToolCall
from kernel.tool_dispatch import execute_tool_call


def _router_returning(text: str) -> MagicMock:
    router = MagicMock()
    router.route = AsyncMock(
        return_value=LLMResponse(text=text, tool_calls=None, provider_used="openai", latency_ms=0)
    )
    return router


async def test_skill_tool_routes_through_skill_executor() -> None:
    state = MagicMock()
    manifest = MagicMock()
    manifest.protocol = "skill"
    state.plugin_registry.get.return_value = manifest
    state.skill_executor.execute = AsyncMock(return_value={"ok": True})
    router = _router_returning("Записал, сэр.")

    call = ToolCall(name="water-tracker__log", arguments={"amount": 200})
    out = await execute_tool_call(state, router, call, [], "запиши воду")

    assert out is not None
    text, result, source = out
    state.skill_executor.execute.assert_awaited_once_with("water-tracker", "log", {"amount": 200})
    assert result == {"ok": True}
    assert text == "Записал, сэр."
    assert source == "agent-water-tracker"


async def test_native_tool_auto_loads_then_dispatches() -> None:
    """First use of a non-eager native agent must auto-load before dispatch
    instead of raising 'not loaded' (core-loop 1b)."""
    state = MagicMock()
    manifest = MagicMock()
    manifest.protocol = "native"
    state.plugin_registry.get.return_value = manifest
    state.agent_runtime.load_agent = AsyncMock()
    state.agent_runtime.dispatch = AsyncMock(return_value={"events": []})
    router = _router_returning("В календаре пусто, сэр.")

    call = ToolCall(name="calendar__list_events", arguments={})
    out = await execute_tool_call(state, router, call, [], "что в календаре")

    assert out is not None
    text, _result, source = out
    state.agent_runtime.load_agent.assert_awaited_once_with("calendar")
    state.agent_runtime.dispatch.assert_awaited_once_with("calendar", "list_events", {})
    assert text == "В календаре пусто, сэр."
    assert source == "agent-calendar"


async def test_dispatch_continues_when_autoload_fails() -> None:
    """A load failure is non-fatal — dispatch still runs and surfaces the real
    error/result rather than aborting the whole turn."""
    state = MagicMock()
    manifest = MagicMock()
    manifest.protocol = "native"
    state.plugin_registry.get.return_value = manifest
    state.agent_runtime.load_agent = AsyncMock(side_effect=RuntimeError("already gone"))
    state.agent_runtime.dispatch = AsyncMock(return_value={"done": True})
    router = _router_returning("Готово.")

    call = ToolCall(name="weather__current", arguments={})
    out = await execute_tool_call(state, router, call, [], "погода")

    assert out is not None
    state.agent_runtime.dispatch.assert_awaited_once()


async def test_list_my_agents_enumerates_registered_agents() -> None:
    """The built-in list tool reports the user's agents (with running status)
    instead of misrouting 'проверь моих агентов' to the tasks agent (2b)."""
    state = MagicMock()
    cal = MagicMock()
    cal.name, cal.description = "calendar", "Календарь"
    water = MagicMock()
    water.name, water.description = "water-tracker", "Вода"
    state.plugin_registry.list_registered.return_value = [cal, water]
    state.agent_runtime.list_agents.return_value = [{"name": "calendar", "status": "running"}]
    router = _router_returning("У тебя есть Календарь и трекер воды, сэр.")

    from kernel.tool_dispatch import LIST_AGENTS_TOOL_NAME

    call = ToolCall(name=LIST_AGENTS_TOOL_NAME, arguments={})
    out = await execute_tool_call(state, router, call, [], "проверь моих агентов")

    assert out is not None
    text, result, source = out
    assert result["count"] == 2
    by_name = {a["name"]: a for a in result["agents"]}
    assert set(by_name) == {"calendar", "water-tracker"}
    assert by_name["calendar"]["running"] is True
    assert by_name["water-tracker"]["running"] is False
    assert source == "agent-kali"
    state.agent_runtime.dispatch.assert_not_called()  # no agent dispatch, just a list


async def test_non_tool_name_returns_none() -> None:
    state = MagicMock()
    router = _router_returning("x")
    call = ToolCall(name="bare_name_no_separator", arguments={})
    assert await execute_tool_call(state, router, call, [], "hi") is None


async def test_execute_tool_calls_dispatches_all_and_combines() -> None:
    """A multi-intent turn must run EVERY tool call (capped), not just the first,
    and surface all results — chat/voice/remote share this one path."""
    from kernel.tool_dispatch import execute_tool_calls

    state = MagicMock()
    skill = MagicMock()
    skill.protocol = "skill"
    state.plugin_registry.get.return_value = skill
    state.skill_executor.execute = AsyncMock(return_value={"ok": True})

    # Each second-pass summary echoes the call so we can assert both appear.
    router = MagicMock()
    summaries = iter(["Записал воду.", "Поставил напоминание."])

    async def _route(_req):  # type: ignore[no-untyped-def]
        return LLMResponse(
            text=next(summaries), tool_calls=None, provider_used="openai", latency_ms=0
        )

    router.route = AsyncMock(side_effect=_route)

    calls = [
        ToolCall(name="water-tracker__log", arguments={"amount": 200}),
        ToolCall(name="reminders__add", arguments={"text": "позвонить"}),
    ]
    out = await execute_tool_calls(state, router, calls, [], "запиши воду и напомни позвонить")

    assert out is not None
    text, results, _source = out
    # Both tools dispatched.
    assert state.skill_executor.execute.await_count == 2
    # Both NL results present in the combined reply — neither silently dropped.
    assert "Записал воду." in text
    assert "Поставил напоминание." in text
    assert len(results) == 2


async def test_execute_tool_calls_caps_at_three() -> None:
    """More than the cap is bounded — we don't fan out an unbounded chain."""
    from kernel.tool_dispatch import execute_tool_calls

    state = MagicMock()
    skill = MagicMock()
    skill.protocol = "skill"
    state.plugin_registry.get.return_value = skill
    state.skill_executor.execute = AsyncMock(return_value={"ok": True})
    router = _router_returning("ок")

    calls = [ToolCall(name=f"a__b{i}", arguments={}) for i in range(5)]
    out = await execute_tool_calls(state, router, calls, [], "много всего")

    assert out is not None
    assert state.skill_executor.execute.await_count == 3
