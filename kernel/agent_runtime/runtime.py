"""Agent runtime — manages agent lifecycle, loading, dispatching."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kernel.agent_runtime.protocols.base import AgentProtocol
from kernel.agent_runtime.protocols.http_client import HttpProtocol
from kernel.agent_runtime.protocols.native import NativeProtocol
from kernel.event_bus import EventBus
from kernel.models import AgentManifest, Event
from kernel.plugin_registry import PluginRegistry

if TYPE_CHECKING:
    from kernel.sandbox.network_proxy import NetworkProxy
    from kernel.sandbox.permission_enforcer import PermissionEnforcer

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


class AgentRuntime:
    """Manages agent lifecycle — load, dispatch, health check, unload."""

    def __init__(
        self,
        registry: PluginRegistry,
        agents_dir: Path,
        event_bus: EventBus,
        enforcer: PermissionEnforcer | None = None,
        network_proxy: NetworkProxy | None = None,
    ) -> None:
        self._registry = registry
        self._agents_dir = agents_dir
        self._bus = event_bus
        self._enforcer = enforcer
        self._network_proxy = network_proxy
        self._agents: dict[str, AgentProtocol] = {}
        self._statuses: dict[str, AgentStatus] = {}

    def _create_protocol(self, manifest: AgentManifest) -> AgentProtocol:
        if manifest.protocol == "native":
            script = self._agents_dir / manifest.name / "agent.py"
            return NativeProtocol(agent_name=manifest.name, script_path=script)
        elif manifest.protocol == "http":
            return HttpProtocol(agent_name=manifest.name, base_url="http://localhost:8080")
        elif manifest.protocol == "skill":
            raise ValueError(
                f"Skill '{manifest.name}' handled by SkillExecutor, not AgentRuntime"
            )
        else:
            raise ValueError(f"Unsupported protocol: {manifest.protocol}")

    async def load_agent(self, name: str) -> None:
        manifest = self._registry.get(name)
        if manifest is None:
            raise ValueError(f"Agent '{name}' not found in registry")

        if name in self._agents:
            logger.warning("Agent '%s' already loaded", name)
            return

        protocol = self._create_protocol(manifest)
        await protocol.start()

        if self._network_proxy and hasattr(protocol, "set_network_proxy"):
            protocol.set_network_proxy(self._network_proxy)

        if self._enforcer:
            self._enforcer.register_agent(name, manifest)
        if self._network_proxy:
            domains = manifest.permissions.get_params("network").get("domains", [])
            if domains:
                self._network_proxy.set_allowed_domains(name, domains)

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

    def is_loaded(self, name: str) -> bool:
        """Return True only if the agent is present AND its process is alive.

        Membership in ``_agents`` is process-presence, not liveness: a crashed
        or exited subprocess stays parked there (only ``unload_agent`` removes
        it). Liveness is the protocol's ``is_running`` signal, so a
        present-but-dead agent reports False.
        """
        protocol = self._agents.get(name)
        return protocol is not None and protocol.is_running

    async def ensure_loaded(self, name: str) -> None:
        """Guarantee a live agent for ``name``, re-spawning a dead one if needed.

        Idempotent when the agent is already live. If it is present but dead,
        the stale entry is unloaded before a fresh load; if absent, it is
        loaded.
        """
        if self.is_loaded(name):
            return
        if name in self._agents:
            # Present but dead — clear the stale subprocess before re-spawning.
            logger.info("Agent '%s' present but not running — re-spawning", name)
            await self.unload_agent(name)
        await self.load_agent(name)

    async def dispatch(self, agent_name: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
        protocol = self._agents.get(agent_name)
        if protocol is None:
            raise ValueError(f"Agent '{agent_name}' is not loaded")

        # Check permissions before dispatch. Pass the concrete action so the
        # enforcer can apply the declaration-scoped, deny-by-default gate to
        # destructive actions (M2.1) — a bare "execute" cannot be proven safe.
        if self._enforcer:
            if not self._enforcer.can_execute(agent_name, f"execute:{action}"):
                raise PermissionError(
                    f"Agent '{agent_name}' not authorized for action '{action}'"
                )

        try:
            return await protocol.execute(action, args)
        except Exception:
            # A per-call failure (bad arg, unknown action, city not found) is
            # NOT a process failure — the agent is still alive and the error is
            # returned to the caller. Flipping the agent to a sticky ERROR
            # status made one bad call look like a permanently broken agent in
            # the UI. Status now reflects process liveness only.
            logger.exception("Agent '%s' dispatch failed", agent_name)
            raise

    async def get_status(self, name: str) -> dict[str, Any]:
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
        return [{"name": name, "status": self._statuses[name].value} for name in self._agents]

    async def shutdown_all(self) -> None:
        for name in list(self._agents.keys()):
            await self.unload_agent(name)
        logger.info("All agents shut down")
