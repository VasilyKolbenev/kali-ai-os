"""Tests for agent runtime manager."""

from pathlib import Path

import pytest
import yaml

from kernel.agent_runtime.runtime import AgentRuntime, AgentStatus
from kernel.event_bus import EventBus
from kernel.plugin_registry import PluginRegistry


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "test-agent"
    agent_dir.mkdir()
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "test-agent",
                "version": "1.0.0",
                "description": "Test agent",
                "capabilities": ["test.hello"],
                "tools": [{"name": "greet", "description": "Greet", "parameters": {}}],
                "protocol": "native",
            }
        )
    )
    src = Path("agents/_example/agent.py")
    if src.exists():
        (agent_dir / "agent.py").write_text(src.read_text())
    return tmp_path


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def runtime(agents_dir: Path, event_bus: EventBus) -> AgentRuntime:
    registry = PluginRegistry(agents_dir)
    registry.discover()
    return AgentRuntime(registry=registry, agents_dir=agents_dir, event_bus=event_bus)


class TestAgentStatus:
    def test_status_values(self) -> None:
        assert AgentStatus.STOPPED.value == "stopped"
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.ERROR.value == "error"


class TestAgentRuntime:
    def test_create_runtime(self, runtime: AgentRuntime) -> None:
        assert len(runtime.list_agents()) == 0

    async def test_load_agent(self, runtime: AgentRuntime) -> None:
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        await runtime.load_agent("test-agent")
        agents = runtime.list_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "test-agent"
        assert agents[0]["status"] == "running"
        await runtime.unload_agent("test-agent")

    async def test_unload_agent(self, runtime: AgentRuntime) -> None:
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        await runtime.load_agent("test-agent")
        await runtime.unload_agent("test-agent")
        assert len(runtime.list_agents()) == 0

    async def test_dispatch_tool_call(self, runtime: AgentRuntime) -> None:
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        await runtime.load_agent("test-agent")
        result = await runtime.dispatch("test-agent", "say_hello", {"name": "Jarvis"})
        assert "Hello" in str(result)
        await runtime.unload_agent("test-agent")

    async def test_get_agent_status(self, runtime: AgentRuntime) -> None:
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        await runtime.load_agent("test-agent")
        status = await runtime.get_status("test-agent")
        assert status["status"] == "running"
        await runtime.unload_agent("test-agent")
