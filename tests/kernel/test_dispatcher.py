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
        dispatcher._runtime.load_agent = AsyncMock()
        dispatcher._runtime._agents = {}

        await dispatcher.dispatch("calendar__get_events", {"date": "today"})
        dispatcher._runtime.load_agent.assert_called_once_with("calendar")
