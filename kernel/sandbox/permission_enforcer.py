"""Runtime permission enforcement for sandboxed agents."""

import logging
from typing import Any

from kernel.models import AgentManifest, PermissionSet

logger = logging.getLogger(__name__)

METHOD_PERMISSIONS: dict[str, str] = {
    "network.request": "network",
    "subscribe_event": "event_bus",
    "publish_event": "event_bus",
    "send_notification": "notifications",
    "call_agent": "agents",
    "get_system_info": "system",
}


class PermissionEnforcer:
    """Validates agent actions against their approved permission set.

    Agents must be registered via ``register_agent`` and their
    ``PermissionSet.user_approved`` flag must be True before any
    permission-gated RPC method is allowed.
    """

    def __init__(self) -> None:
        """Initialise the enforcer with an empty registry."""
        self._permissions: dict[str, PermissionSet] = {}

    def register_agent(self, agent_name: str, manifest: AgentManifest) -> None:
        """Register an agent's permission set from its manifest.

        Args:
            agent_name: Unique agent identifier.
            manifest: Parsed AgentManifest containing the PermissionSet.
        """
        self._permissions[agent_name] = manifest.permissions
        logger.debug("Registered permissions for agent '%s'", agent_name)

    def can_execute(self, agent_name: str, rpc_method: str) -> bool:
        """Check whether an agent is allowed to call an RPC method.

        Args:
            agent_name: Unique agent identifier.
            rpc_method: RPC method name being invoked.

        Returns:
            True if the agent has the required permission and user approval.
        """
        perms = self._permissions.get(agent_name)
        if not perms:
            logger.warning("Agent '%s' not registered in enforcer", agent_name)
            return False
        if not perms.user_approved:
            logger.warning("Agent '%s' permissions not user-approved", agent_name)
            return False
        required = METHOD_PERMISSIONS.get(rpc_method)
        if required is None:
            # Unknown method — no permission required
            return True
        return perms.has(required)

    def get_network_domains(self, agent_name: str) -> list[str]:
        """Return the allowed network domains for an agent.

        Args:
            agent_name: Unique agent identifier.

        Returns:
            List of domain patterns from the network permission params.
        """
        perms = self._permissions.get(agent_name)
        if not perms:
            return []
        return perms.get_params("network").get("domains", [])
