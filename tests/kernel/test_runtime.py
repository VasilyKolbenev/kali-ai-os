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
    """Minimal AgentProtocol stand-in that records executed actions.

    ``is_running`` is controllable to simulate a present-but-dead subprocess.
    """

    def __init__(self, *, running: bool = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.running = running

    @property
    def is_running(self) -> bool:
        return self.running

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


class TestIsLoadedEnsureLoaded:
    """Task 2.7: liveness-aware is_loaded + self-healing ensure_loaded.

    Guards the divergent-liveness bug: a present-but-dead subprocess (still in
    ``_agents`` because only ``unload_agent`` removes it) must NOT pass as
    loaded, and ``ensure_loaded`` must transparently re-spawn it.
    """

    def _runtime(self) -> AgentRuntime:
        return AgentRuntime(
            registry=PluginRegistry(Path(".")),
            agents_dir=Path("."),
            event_bus=EventBus(),
        )

    def test_is_loaded_false_when_absent(self) -> None:
        rt = self._runtime()
        assert rt.is_loaded("ghost") is False

    def test_is_loaded_true_for_live_protocol(self) -> None:
        rt = self._runtime()
        rt._agents["live"] = _FakeProtocol(running=True)  # type: ignore[assignment]
        assert rt.is_loaded("live") is True

    def test_is_loaded_false_for_present_but_dead_protocol(self) -> None:
        rt = self._runtime()
        # Simulates a crashed/exited subprocess still parked in _agents.
        rt._agents["dead"] = _FakeProtocol(running=False)  # type: ignore[assignment]
        assert rt.is_loaded("dead") is False

    async def test_ensure_loaded_noop_when_already_live(self) -> None:
        rt = self._runtime()
        proto = _FakeProtocol(running=True)
        rt._agents["live"] = proto  # type: ignore[assignment]

        async def _fail_load(name: str) -> None:
            raise AssertionError("load_agent must not be called for a live agent")

        rt.load_agent = _fail_load  # type: ignore[assignment]
        await rt.ensure_loaded("live")
        assert rt._agents["live"] is proto  # unchanged

    async def test_ensure_loaded_loads_when_absent(self) -> None:
        rt = self._runtime()
        loaded: list[str] = []

        async def _load(name: str) -> None:
            loaded.append(name)
            rt._agents[name] = _FakeProtocol(running=True)  # type: ignore[assignment]

        rt.load_agent = _load  # type: ignore[assignment]
        await rt.ensure_loaded("fresh")
        assert loaded == ["fresh"]
        assert rt.is_loaded("fresh") is True

    async def test_ensure_loaded_respawns_dead_agent(self) -> None:
        rt = self._runtime()
        dead = _FakeProtocol(running=False)
        rt._agents["svc"] = dead  # type: ignore[assignment]
        unloaded: list[str] = []
        loaded: list[str] = []

        async def _unload(name: str) -> None:
            unloaded.append(name)
            rt._agents.pop(name, None)

        async def _load(name: str) -> None:
            loaded.append(name)
            rt._agents[name] = _FakeProtocol(running=True)  # type: ignore[assignment]

        rt.unload_agent = _unload  # type: ignore[assignment]
        rt.load_agent = _load  # type: ignore[assignment]

        await rt.ensure_loaded("svc")

        # Stale entry unloaded, then a fresh live protocol loaded.
        assert unloaded == ["svc"]
        assert loaded == ["svc"]
        assert rt.is_loaded("svc") is True
        assert rt._agents["svc"] is not dead

    async def test_ensure_loaded_then_dispatch_succeeds_after_respawn(self) -> None:
        rt = self._runtime()
        rt._agents["svc"] = _FakeProtocol(running=False)  # type: ignore[assignment]

        async def _unload(name: str) -> None:
            rt._agents.pop(name, None)

        async def _load(name: str) -> None:
            rt._agents[name] = _FakeProtocol(running=True)  # type: ignore[assignment]

        rt.unload_agent = _unload  # type: ignore[assignment]
        rt.load_agent = _load  # type: ignore[assignment]

        await rt.ensure_loaded("svc")
        result = await rt.dispatch("svc", "do", {"x": 1})
        assert result == {"status": "ok"}
