"""Tests for agent runtime manager."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from kernel.agent_runtime.runtime import AgentRuntime, AgentStatus
from kernel.event_bus import EventBus
from kernel.models import AgentManifest, PermissionSet
from kernel.plugin_registry import PluginRegistry
from kernel.sandbox.permission_enforcer import PermissionEnforcer


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


class _FakeProtocol:
    """Minimal AgentProtocol stand-in that records executed actions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, args))
        return {"status": "ok"}


def _manifest(name: str, capabilities: list[str], *, approved: bool) -> AgentManifest:
    return AgentManifest(
        name=name,
        version="1.0.0",
        description="Test",
        capabilities=capabilities,
        permissions=PermissionSet(grants=[], user_approved=approved),
    )


class TestDispatchPermissionGate:
    """M2.1: voice/chat dispatch is action-aware (passes execute:{action})."""

    def _runtime_with(self, manifest: AgentManifest, proto: _FakeProtocol) -> AgentRuntime:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(manifest.name, manifest)
        rt = AgentRuntime(
            registry=PluginRegistry(Path(".")),
            agents_dir=Path("."),
            event_bus=EventBus(),
            enforcer=enforcer,
        )
        rt._agents[manifest.name] = proto  # type: ignore[assignment]
        return rt

    async def test_destructive_undeclared_raises_permission_error(self) -> None:
        proto = _FakeProtocol()
        # Approved, but declares only a read-class capability.
        rt = self._runtime_with(
            _manifest("calendar", ["calendar.read"], approved=True), proto
        )
        with pytest.raises(PermissionError):
            await rt.dispatch("calendar", "delete_event", {"event_id": "1"})
        # Protocol must NOT have been reached.
        assert proto.calls == []

    async def test_destructive_declared_dispatches(self) -> None:
        proto = _FakeProtocol()
        rt = self._runtime_with(
            _manifest("calendar", ["calendar.read", "calendar.write"], approved=True),
            proto,
        )
        result = await rt.dispatch("calendar", "delete_event", {"event_id": "1"})
        assert result == {"status": "ok"}
        assert proto.calls == [("delete_event", {"event_id": "1"})]

    async def test_non_destructive_dispatches(self) -> None:
        proto = _FakeProtocol()
        rt = self._runtime_with(
            _manifest("weather", [], approved=True), proto
        )
        result = await rt.dispatch("weather", "get_weather", {"city": "Moscow"})
        assert result == {"status": "ok"}
        assert proto.calls == [("get_weather", {"city": "Moscow"})]
