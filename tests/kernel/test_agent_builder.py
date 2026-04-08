"""Tests for no-code agent builder."""

from pathlib import Path

import pytest

from kernel.agent_builder import AgentBuilder
from kernel.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def builder(bus: EventBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentBuilder:
    custom_dir = tmp_path / "custom"
    monkeypatch.setattr("kernel.agent_builder.CUSTOM_AGENTS_DIR", custom_dir)
    return AgentBuilder(bus)


class TestAgentBuilder:
    def test_create_agent(self, builder: AgentBuilder) -> None:
        result = builder.create_agent(
            name="test-monitor",
            description="Test monitoring agent",
            tools=[{"name": "check", "description": "Run check", "parameters": {}}],
            action_code=(
                'if action == "check":\n    return {"status": "ok"}\n'
                'else:\n    raise ValueError(f"Unknown: {action}")'
            ),
        )
        assert result["status"] == "created"
        assert result["name"] == "test-monitor"

    def test_create_from_monitor_template(self, builder: AgentBuilder) -> None:
        result = builder.create_from_template("price-checker", "Price monitoring", "monitor")
        assert result["status"] == "created"

    def test_create_from_tracker_template(self, builder: AgentBuilder) -> None:
        result = builder.create_from_template("weight-tracker", "Body weight tracking", "tracker")
        assert result["status"] == "created"

    def test_create_from_notifier_template(self, builder: AgentBuilder) -> None:
        result = builder.create_from_template("alert-bot", "Custom alerts", "notifier")
        assert result["status"] == "created"

    def test_safety_check_blocks_dangerous_code(self, builder: AgentBuilder) -> None:
        result = builder.create_agent(
            name="evil",
            description="Bad agent",
            tools=[],
            action_code='os.system("rm -rf /")',
        )
        assert result["status"] == "error"
        assert "Safety" in result["message"]

    def test_safety_check_blocks_eval(self, builder: AgentBuilder) -> None:
        result = builder.create_agent(
            name="evil2",
            description="Bad agent",
            tools=[],
            action_code='eval("malicious")',
        )
        assert result["status"] == "error"

    def test_list_custom_agents(self, builder: AgentBuilder) -> None:
        builder.create_from_template("test-agent", "Test", "monitor")
        agents = builder.list_custom_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "test-agent"

    def test_delete_agent(self, builder: AgentBuilder) -> None:
        builder.create_from_template("temp-agent", "Temporary", "monitor")
        result = builder.delete_agent("temp-agent")
        assert result["status"] == "deleted"
        assert len(builder.list_custom_agents()) == 0

    def test_invalid_name_sanitized(self, builder: AgentBuilder) -> None:
        result = builder.create_from_template("My Cool Agent!!!", "Test", "monitor")
        assert result["status"] == "created"
        assert result["name"] == "my-cool-agent"

    def test_unknown_template(self, builder: AgentBuilder) -> None:
        result = builder.create_from_template("test", "Test", "nonexistent")
        assert result["status"] == "error"
