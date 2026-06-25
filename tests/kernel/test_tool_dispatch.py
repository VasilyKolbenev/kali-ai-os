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


async def test_non_tool_name_returns_none() -> None:
    state = MagicMock()
    router = _router_returning("x")
    call = ToolCall(name="bare_name_no_separator", arguments={})
    assert await execute_tool_call(state, router, call, [], "hi") is None
