"""Tests for agent plugin registry."""

from pathlib import Path

import pytest
import yaml

from kernel.plugin_registry import PluginRegistry


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    cal_dir = tmp_path / "calendar"
    cal_dir.mkdir()
    (cal_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "calendar",
                "version": "1.0.0",
                "description": "Calendar agent",
                "capabilities": ["calendar.read", "calendar.write"],
                "tools": [{"name": "get_events", "description": "Get events", "parameters": {}}],
                "protocol": "native",
                "permissions": ["network"],
            }
        )
    )

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "tasks",
                "version": "1.0.0",
                "description": "Tasks agent",
                "capabilities": ["tasks.read", "tasks.write"],
                "protocol": "native",
            }
        )
    )

    return tmp_path


@pytest.fixture
def registry(agents_dir: Path) -> PluginRegistry:
    return PluginRegistry(agents_dir)


class TestPluginRegistry:
    def test_discover_agents(self, registry: PluginRegistry) -> None:
        agents = registry.discover()
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"calendar", "tasks"}

    def test_get_agent_by_name(self, registry: PluginRegistry) -> None:
        registry.discover()
        agent = registry.get("calendar")
        assert agent is not None
        assert agent.name == "calendar"

    def test_get_missing_agent_returns_none(self, registry: PluginRegistry) -> None:
        registry.discover()
        assert registry.get("nonexistent") is None

    def test_get_all_tools(self, registry: PluginRegistry) -> None:
        registry.discover()
        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "calendar__get_events"

    def test_find_agent_by_tool_name(self, registry: PluginRegistry) -> None:
        registry.discover()
        agent = registry.find_agent_for_tool("calendar__get_events")
        assert agent is not None
        assert agent.name == "calendar"

    def test_skip_invalid_manifest(self, agents_dir: Path) -> None:
        bad_dir = agents_dir / "broken"
        bad_dir.mkdir()
        (bad_dir / "manifest.yaml").write_text("not: valid: yaml: [")

        registry = PluginRegistry(agents_dir)
        agents = registry.discover()
        assert len(agents) == 2

    def test_skip_dir_without_manifest(self, agents_dir: Path) -> None:
        (agents_dir / "no_manifest").mkdir()
        registry = PluginRegistry(agents_dir)
        agents = registry.discover()
        assert len(agents) == 2

    def test_list_registered(self, registry: PluginRegistry) -> None:
        registry.discover()
        registered = registry.list_registered()
        assert len(registered) == 2
