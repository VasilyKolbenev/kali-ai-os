# Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the agent runtime — subprocess management, JSON-RPC native protocol, HTTP protocol client, agent lifecycle (load/dispatch/health/shutdown), and wire it into the kernel so LLM tool calls are dispatched to real agents.

**Architecture:** Agents run as isolated subprocesses communicating via stdin/stdout JSON-RPC (native protocol) or HTTP REST (http protocol). The runtime manages lifecycle, health checks, restart on failure, and dispatches tool calls from the LLM Router to the correct agent.

**Tech Stack:** Python 3.12+, asyncio subprocesses, JSON-RPC 2.0, httpx, existing kernel components

**Spec:** `docs/superpowers/specs/2026-04-08-jarvis-2026-design.md`

---

## File Structure

```
kernel/
  agent_runtime/
    __init__.py
    runtime.py              # Agent lifecycle manager
    protocols/
      __init__.py
      base.py               # Protocol ABC
      native.py             # JSON-RPC stdin/stdout
      http_client.py        # HTTP REST client
    dispatcher.py           # Tool call -> agent dispatch
agents/
  _example/
    manifest.yaml           # (exists)
    agent.py                # Example native agent (new)
tests/
  kernel/
    test_native_protocol.py
    test_http_protocol.py
    test_runtime.py
    test_dispatcher.py
```

---

## Chunk 1: Protocol Base + Native Protocol

### Task 1: Protocol Base Class + Native JSON-RPC Protocol

**Files:**
- Create: `kernel/agent_runtime/__init__.py`
- Create: `kernel/agent_runtime/protocols/__init__.py`
- Create: `kernel/agent_runtime/protocols/base.py`
- Create: `kernel/agent_runtime/protocols/native.py`
- Create: `agents/_example/agent.py`
- Create: `tests/kernel/test_native_protocol.py`

- [ ] **Step 1: Write tests**

Create `tests/kernel/test_native_protocol.py`:

```python
"""Tests for native JSON-RPC protocol."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from kernel.agent_runtime.protocols.native import NativeProtocol


@pytest.fixture
def example_agent_path() -> Path:
    return Path("agents/_example/agent.py")


class TestNativeProtocol:
    def test_create_protocol(self) -> None:
        proto = NativeProtocol(agent_name="test", script_path=Path("test.py"))
        assert proto.agent_name == "test"
        assert not proto.is_running

    async def test_start_and_stop_example_agent(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        assert proto.is_running
        await proto.stop()
        assert not proto.is_running

    async def test_health_check(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        result = await proto.health()
        assert result["status"] == "healthy"
        await proto.stop()

    async def test_execute_tool(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        result = await proto.execute("say_hello", {"name": "World"})
        assert "Hello" in result.get("message", result.get("text", ""))
        await proto.stop()

    async def test_initialize(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        result = await proto.initialize({"test": True})
        assert result.get("status") == "ok"
        await proto.stop()
```

- [ ] **Step 2: Implement protocol base and native**

Create `kernel/agent_runtime/__init__.py`:
```python
"""Agent runtime — subprocess management and protocol communication."""
```

Create `kernel/agent_runtime/protocols/__init__.py`:
```python
"""Agent communication protocols."""
```

Create `kernel/agent_runtime/protocols/base.py`:
```python
"""Base protocol interface for agent communication."""

import abc
from typing import Any


class AgentProtocol(abc.ABC):
    """Abstract base for agent communication protocols."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Start the agent process/connection."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop the agent process/connection."""

    @abc.abstractmethod
    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]:
        """Send initialization config to agent."""

    @abc.abstractmethod
    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool action on the agent."""

    @abc.abstractmethod
    async def health(self) -> dict[str, Any]:
        """Check agent health."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shut down the agent."""

    @property
    @abc.abstractmethod
    def is_running(self) -> bool:
        """Whether the agent is currently running."""
```

Create `kernel/agent_runtime/protocols/native.py`:
```python
"""Native JSON-RPC protocol — communicates with agents via stdin/stdout."""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from kernel.agent_runtime.protocols.base import AgentProtocol

logger = logging.getLogger(__name__)


class NativeProtocol(AgentProtocol):
    """Communicates with agent subprocesses via stdin/stdout JSON-RPC 2.0."""

    def __init__(self, agent_name: str, script_path: Path) -> None:
        self.agent_name = agent_name
        self._script_path = script_path
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if self.is_running:
            return
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, str(self._script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("Agent '%s' started (pid=%d)", self.agent_name, self._process.pid)

    async def stop(self) -> None:
        if not self.is_running:
            return
        try:
            await self.shutdown()
        except Exception:
            pass
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
        self._process = None
        logger.info("Agent '%s' stopped", self.agent_name)

    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self._send("initialize", {"config": config})

    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._send("execute", {"action": action, "args": args})

    async def health(self) -> dict[str, Any]:
        return await self._send("health", {})

    async def shutdown(self) -> None:
        try:
            await self._send("shutdown", {})
        except Exception:
            pass

    async def _send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and read the response."""
        if not self.is_running or not self._process:
            raise RuntimeError(f"Agent '{self.agent_name}' is not running")

        async with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": self._request_id,
            }
            line = json.dumps(request) + "\n"

            assert self._process.stdin is not None
            assert self._process.stdout is not None

            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

            response_line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=10.0
            )

            if not response_line:
                raise RuntimeError(f"Agent '{self.agent_name}' closed stdout")

            response = json.loads(response_line.decode().strip())

            if "error" in response:
                raise RuntimeError(
                    f"Agent error: {response['error'].get('message', 'unknown')}"
                )

            return response.get("result", {})
```

- [ ] **Step 3: Create example agent**

Create `agents/_example/agent.py`:
```python
"""Example native agent — reads JSON-RPC from stdin, writes to stdout."""

import json
import sys
import time

START_TIME = time.time()


def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request."""
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    if method == "initialize":
        result = {"status": "ok"}
    elif method == "execute":
        action = params.get("action", "")
        args = params.get("args", {})
        if action == "say_hello":
            name = args.get("name", "World")
            result = {"message": f"Hello, {name}!"}
        else:
            result = {"error": f"Unknown action: {action}"}
    elif method == "health":
        result = {"status": "healthy", "uptime_s": int(time.time() - START_TIME)}
    elif method == "shutdown":
        result = {"status": "ok"}
        response = {"jsonrpc": "2.0", "result": result, "id": request_id}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
        sys.exit(0)
    else:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": request_id,
        }

    return {"jsonrpc": "2.0", "result": result, "id": request_id}


def main() -> None:
    """Main loop — read JSON-RPC from stdin, write to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — should PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: native JSON-RPC protocol with example agent"
```

---

## Chunk 2: HTTP Protocol + Runtime Manager

### Task 2: HTTP Protocol Client

**Files:**
- Create: `kernel/agent_runtime/protocols/http_client.py`
- Create: `tests/kernel/test_http_protocol.py`

- [ ] **Step 1: Write tests**

Create `tests/kernel/test_http_protocol.py`:

```python
"""Tests for HTTP protocol client."""

import pytest

from kernel.agent_runtime.protocols.http_client import HttpProtocol


class TestHttpProtocol:
    def test_create_protocol(self) -> None:
        proto = HttpProtocol(agent_name="smart-home", base_url="http://localhost:8080")
        assert proto.agent_name == "smart-home"
        assert proto.base_url == "http://localhost:8080"
        assert not proto.is_running

    def test_default_timeout(self) -> None:
        proto = HttpProtocol(agent_name="test", base_url="http://localhost:8080")
        assert proto.timeout == 30.0

    async def test_start_sets_running(self) -> None:
        proto = HttpProtocol(agent_name="test", base_url="http://localhost:8080")
        await proto.start()
        assert proto.is_running
        await proto.stop()
        assert not proto.is_running
```

- [ ] **Step 2: Implement HTTP protocol**

Create `kernel/agent_runtime/protocols/http_client.py`:
```python
"""HTTP REST protocol — communicates with agents via HTTP API."""

import logging
from typing import Any

import httpx

from kernel.agent_runtime.protocols.base import AgentProtocol

logger = logging.getLogger(__name__)


class HttpProtocol(AgentProtocol):
    """Communicates with HTTP-based agents (e.g., Home Assistant)."""

    def __init__(
        self,
        agent_name: str,
        base_url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = headers or {}
        self._client: httpx.AsyncClient | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._headers,
        )
        self._running = True
        logger.info("HTTP agent '%s' connected at %s", self.agent_name, self.base_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._running = False

    async def initialize(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/initialize", config)

    async def execute(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/execute", {"action": action, "args": args})

    async def health(self) -> dict[str, Any]:
        if not self._client:
            return {"status": "disconnected"}
        try:
            resp = await self._client.get("/health")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def shutdown(self) -> None:
        try:
            await self._post("/shutdown", {})
        except Exception:
            pass

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError(f"Agent '{self.agent_name}' not connected")
        resp = await self._client.post(path, json=data)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 3: Run tests — should PASS**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat: HTTP protocol client for REST-based agents"
```

---

### Task 3: Agent Runtime Manager

**Files:**
- Create: `kernel/agent_runtime/runtime.py`
- Create: `tests/kernel/test_runtime.py`

- [ ] **Step 1: Write tests**

Create `tests/kernel/test_runtime.py`:

```python
"""Tests for agent runtime manager."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from kernel.agent_runtime.runtime import AgentRuntime, AgentStatus
from kernel.event_bus import EventBus
from kernel.models import AgentManifest
from kernel.plugin_registry import PluginRegistry


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "test-agent"
    agent_dir.mkdir()
    (agent_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "test-agent",
        "version": "1.0.0",
        "description": "Test agent",
        "capabilities": ["test.hello"],
        "tools": [{"name": "greet", "description": "Greet", "parameters": {}}],
        "protocol": "native",
    }))
    # Copy example agent script
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
        agents = runtime.list_agents()
        assert len(agents) == 0

    async def test_dispatch_tool_call(self, runtime: AgentRuntime) -> None:
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        await runtime.load_agent("test-agent")
        result = await runtime.dispatch("test-agent", "greet", {"name": "Jarvis"})
        assert "Hello" in str(result) or "message" in result
        await runtime.unload_agent("test-agent")

    async def test_get_agent_status(self, runtime: AgentRuntime) -> None:
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        await runtime.load_agent("test-agent")
        status = await runtime.get_status("test-agent")
        assert status["status"] == "running"
        await runtime.unload_agent("test-agent")

    def test_load_nonexistent_agent_raises(self, runtime: AgentRuntime) -> None:
        import pytest as pt
        with pt.raises(ValueError, match="not found"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(runtime.load_agent("nonexistent"))
```

- [ ] **Step 2: Implement AgentRuntime**

Create `kernel/agent_runtime/runtime.py`:
```python
"""Agent runtime — manages agent lifecycle, loading, dispatching."""

import logging
from enum import Enum
from pathlib import Path
from typing import Any

from kernel.agent_runtime.protocols.base import AgentProtocol
from kernel.agent_runtime.protocols.http_client import HttpProtocol
from kernel.agent_runtime.protocols.native import NativeProtocol
from kernel.event_bus import EventBus
from kernel.models import AgentManifest, Event
from kernel.plugin_registry import PluginRegistry

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent lifecycle status."""

    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


class AgentRuntime:
    """Manages agent lifecycle — load, dispatch, health check, unload.

    Creates the appropriate protocol (native/http) based on manifest,
    starts agent subprocess, and routes tool calls to agents.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        agents_dir: Path,
        event_bus: EventBus,
    ) -> None:
        self._registry = registry
        self._agents_dir = agents_dir
        self._bus = event_bus
        self._agents: dict[str, AgentProtocol] = {}
        self._statuses: dict[str, AgentStatus] = {}

    def _create_protocol(self, manifest: AgentManifest) -> AgentProtocol:
        """Create the appropriate protocol for an agent."""
        if manifest.protocol == "native":
            script = self._agents_dir / manifest.name / "agent.py"
            return NativeProtocol(agent_name=manifest.name, script_path=script)
        elif manifest.protocol == "http":
            return HttpProtocol(agent_name=manifest.name, base_url="http://localhost:8080")
        else:
            raise ValueError(f"Unsupported protocol: {manifest.protocol}")

    async def load_agent(self, name: str) -> None:
        """Load and start an agent by name."""
        manifest = self._registry.get(name)
        if manifest is None:
            raise ValueError(f"Agent '{name}' not found in registry")

        if name in self._agents:
            logger.warning("Agent '%s' already loaded, skipping", name)
            return

        protocol = self._create_protocol(manifest)
        await protocol.start()

        try:
            await protocol.initialize({})
        except Exception:
            logger.warning("Agent '%s' initialize failed (non-fatal)", name)

        self._agents[name] = protocol
        self._statuses[name] = AgentStatus.RUNNING

        await self._bus.publish(
            Event(
                topic="agent.status.update",
                source="agent-runtime",
                payload={"agent": name, "status": "running"},
            )
        )
        logger.info("Agent '%s' loaded and running", name)

    async def unload_agent(self, name: str) -> None:
        """Stop and unload an agent."""
        protocol = self._agents.pop(name, None)
        if protocol:
            await protocol.stop()
        self._statuses.pop(name, None)

        await self._bus.publish(
            Event(
                topic="agent.status.update",
                source="agent-runtime",
                payload={"agent": name, "status": "stopped"},
            )
        )
        logger.info("Agent '%s' unloaded", name)

    async def dispatch(self, agent_name: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call to an agent."""
        protocol = self._agents.get(agent_name)
        if protocol is None:
            raise ValueError(f"Agent '{agent_name}' is not loaded")

        try:
            result = await protocol.execute(action, args)
            return result
        except Exception as e:
            self._statuses[agent_name] = AgentStatus.ERROR
            logger.exception("Agent '%s' dispatch failed", agent_name)
            raise

    async def get_status(self, name: str) -> dict[str, Any]:
        """Get agent status with health check."""
        protocol = self._agents.get(name)
        if protocol is None:
            return {"name": name, "status": "not_loaded"}

        status = self._statuses.get(name, AgentStatus.STOPPED)
        result: dict[str, Any] = {"name": name, "status": status.value}

        if protocol.is_running:
            try:
                health = await protocol.health()
                result["health"] = health
            except Exception:
                result["health"] = {"status": "unreachable"}

        return result

    def list_agents(self) -> list[dict[str, Any]]:
        """List all loaded agents with their status."""
        return [
            {"name": name, "status": self._statuses[name].value}
            for name in self._agents
        ]

    async def shutdown_all(self) -> None:
        """Gracefully shut down all agents."""
        for name in list(self._agents.keys()):
            await self.unload_agent(name)
        logger.info("All agents shut down")
```

- [ ] **Step 3: Run tests — should PASS**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat: agent runtime with lifecycle management and dispatch"
```

---

## Chunk 3: Dispatcher + FastAPI Integration

### Task 4: Tool Call Dispatcher

**Files:**
- Create: `kernel/agent_runtime/dispatcher.py`
- Create: `tests/kernel/test_dispatcher.py`

- [ ] **Step 1: Write tests**

Create `tests/kernel/test_dispatcher.py`:

```python
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
    (agent_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "calendar",
        "version": "1.0.0",
        "description": "Calendar agent",
        "tools": [{"name": "get_events", "description": "Get events", "parameters": {}}],
        "protocol": "native",
    }))
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
        """Dispatcher should auto-load the agent if not loaded."""
        if not Path("agents/_example/agent.py").exists():
            pytest.skip("Example agent not found")
        # Mock the runtime dispatch to avoid needing a real agent process
        dispatcher._runtime.dispatch = AsyncMock(return_value={"result": "ok"})
        dispatcher._runtime.load_agent = AsyncMock()
        dispatcher._runtime._agents = {}

        result = await dispatcher.dispatch("calendar__get_events", {"date": "today"})
        # Should have tried to load the agent
        dispatcher._runtime.load_agent.assert_called_once_with("calendar")
```

- [ ] **Step 2: Implement ToolDispatcher**

Create `kernel/agent_runtime/dispatcher.py`:
```python
"""Tool call dispatcher — routes LLM tool calls to agents."""

import logging
from typing import Any

from kernel.agent_runtime.runtime import AgentRuntime
from kernel.plugin_registry import PluginRegistry

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches LLM tool calls to the correct agent.

    Tool names follow the format: {agent_name}__{tool_name}.
    Agents are auto-loaded on first dispatch if not already running.
    """

    def __init__(self, runtime: AgentRuntime, registry: PluginRegistry) -> None:
        self._runtime = runtime
        self._registry = registry

    def parse_tool_name(self, tool_name: str) -> tuple[str, str]:
        """Parse a namespaced tool name into (agent_name, action)."""
        if "__" not in tool_name:
            raise ValueError(f"Invalid tool name format: {tool_name} (expected agent__action)")
        parts = tool_name.split("__", 1)
        return parts[0], parts[1]

    async def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate agent.

        Auto-loads the agent if not already running.
        """
        agent_name, action = self.parse_tool_name(tool_name)

        # Verify agent exists in registry
        manifest = self._registry.get(agent_name)
        if manifest is None:
            raise ValueError(f"Agent '{agent_name}' not found in registry")

        # Auto-load if not running
        if agent_name not in self._runtime._agents:
            logger.info("Auto-loading agent '%s' for tool call", agent_name)
            await self._runtime.load_agent(agent_name)

        return await self._runtime.dispatch(agent_name, action, arguments)
```

- [ ] **Step 3: Run tests — should PASS**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat: tool dispatcher for routing LLM tool calls to agents"
```

---

### Task 5: Wire Agent Runtime into FastAPI

**Files:**
- Modify: `kernel/main.py`

- [ ] **Step 1: Add agent runtime to main.py**

Add imports:
```python
from kernel.agent_runtime.runtime import AgentRuntime
from kernel.agent_runtime.dispatcher import ToolDispatcher
```

In the lifespan, after plugin_registry.discover():
```python
        agent_runtime = AgentRuntime(
            registry=plugin_registry,
            agents_dir=resolved_agents_dir,
            event_bus=event_bus,
        )
        tool_dispatcher = ToolDispatcher(
            runtime=agent_runtime,
            registry=plugin_registry,
        )
        app.state.agent_runtime = agent_runtime
        app.state.tool_dispatcher = tool_dispatcher
```

In the shutdown section, before scheduler.stop():
```python
        await agent_runtime.shutdown_all()
```

Add routes:
```python
    @app.get("/agents/running")
    async def running_agents(request: Request) -> list[dict[str, Any]]:
        return request.app.state.agent_runtime.list_agents()

    @app.post("/agents/{name}/load")
    async def load_agent(name: str, request: Request) -> dict[str, str]:
        try:
            await request.app.state.agent_runtime.load_agent(name)
            return {"status": "loaded", "agent": name}
        except ValueError as e:
            return {"status": "error", "message": str(e)}

    @app.post("/agents/{name}/unload")
    async def unload_agent(name: str, request: Request) -> dict[str, str]:
        await request.app.state.agent_runtime.unload_agent(name)
        return {"status": "unloaded", "agent": name}

    @app.get("/agents/{name}/status")
    async def agent_status(name: str, request: Request) -> dict[str, Any]:
        return await request.app.state.agent_runtime.get_status(name)
```

- [ ] **Step 2: Run all tests**
- [ ] **Step 3: Lint and format**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat: wire agent runtime into FastAPI with load/unload/status endpoints"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Run full test suite**
- [ ] **Step 2: Run linter**
- [ ] **Step 3: Start dev server and verify**

```bash
curl -s http://localhost:8001/agents/running
curl -s http://localhost:8001/agents/_example/status
```

- [ ] **Step 4: Commit any fixes**

---

## Summary

After completing all tasks, the agent runtime provides:

1. **AgentProtocol** — abstract base for all protocols
2. **NativeProtocol** — JSON-RPC 2.0 over stdin/stdout
3. **HttpProtocol** — REST API client for HTTP agents
4. **AgentRuntime** — lifecycle manager (load, unload, dispatch, health)
5. **ToolDispatcher** — routes LLM tool calls to agents
6. **Example agent** — reference native agent implementation
7. **FastAPI endpoints** — `/agents/running`, `/agents/{name}/load`, `/agents/{name}/unload`, `/agents/{name}/status`

**Next sub-project:** UI Shell (Tauri + React + Three.js avatar + dashboard)
