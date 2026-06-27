"""Tests for tool call dispatcher."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from kernel.agent_runtime.dispatcher import ToolDispatcher
from kernel.agent_runtime.runtime import AgentRuntime
from kernel.event_bus import EventBus
from kernel.plugin_registry import PluginRegistry


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "calendar"
    agent_dir.mkdir()
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "calendar",
                "version": "1.0.0",
                "description": "Calendar agent",
                "tools": [{"name": "get_events", "description": "Get events", "parameters": {}}],
                "protocol": "native",
            }
        )
    )
    return tmp_path


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def dispatcher(agents_dir: Path, event_bus: EventBus) -> ToolDispatcher:
    registry = PluginRegistry(agents_dir)
    registry.discover()
    runtime = AgentRuntime(registry=registry, agents_dir=agents_dir, event_bus=event_bus)
    return ToolDispatcher(runtime=runtime, registry=registry)


class TestToolDispatcher:
    def test_create_dispatcher(self, dispatcher: ToolDispatcher) -> None:
        assert dispatcher is not None

    def test_parse_tool_name(self, dispatcher: ToolDispatcher) -> None:
        agent, action = dispatcher.parse_tool_name("calendar__get_events")
        assert agent == "calendar"
        assert action == "get_events"

    def test_parse_invalid_tool_name(self, dispatcher: ToolDispatcher) -> None:
        with pytest.raises(ValueError):
            dispatcher.parse_tool_name("invalid_name")

    async def test_dispatch_auto_loads_agent(self, dispatcher: ToolDispatcher) -> None:
        dispatcher._runtime.dispatch = AsyncMock(return_value={"result": "ok"})
        dispatcher._runtime.ensure_loaded = AsyncMock()

        await dispatcher.dispatch("calendar__get_events", {"date": "today"})
        dispatcher._runtime.ensure_loaded.assert_called_once_with("calendar")

    async def test_dispatch_respawns_dead_agent_then_dispatches(
        self, dispatcher: ToolDispatcher
    ) -> None:
        # A dead-but-present agent must be transparently re-loaded by the
        # dispatcher (via ensure_loaded) rather than surfacing a confusing
        # "not loaded" / "closed stdout" error from runtime.dispatch.
        class _Proto:
            def __init__(self, *, running: bool) -> None:
                self.running = running
                self.calls: list[str] = []

            @property
            def is_running(self) -> bool:
                return self.running

            async def execute(self, action: str, args: dict) -> dict:
                self.calls.append(action)
                return {"result": "ok"}

        rt = dispatcher._runtime
        dead = _Proto(running=False)
        rt._agents["calendar"] = dead  # type: ignore[assignment]

        async def _unload(name: str) -> None:
            rt._agents.pop(name, None)

        async def _load(name: str) -> None:
            rt._agents[name] = _Proto(running=True)  # type: ignore[assignment]

        rt.unload_agent = _unload  # type: ignore[assignment]
        rt.load_agent = _load  # type: ignore[assignment]

        result = await dispatcher.dispatch("calendar__get_events", {"date": "today"})
        assert result == {"result": "ok"}
        # The fresh, live protocol handled the call (not the dead one).
        assert rt._agents["calendar"] is not dead
