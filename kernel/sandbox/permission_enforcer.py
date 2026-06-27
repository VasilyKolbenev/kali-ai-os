"""Runtime permission enforcement for sandboxed agents."""

import logging
import re
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

#: Verb tokens that mark an action as destructive, outward-facing, or
#: irreversible. Conservative by design — when an action is ambiguous it is
#: treated as NON-destructive (read/list/get/log/add/create/update-own actions
#: are not listed). Used by :func:`_is_destructive` to gate ``execute:{action}``
#: against an agent's declared capabilities (M2.1, deny-by-default).
DESTRUCTIVE_VERBS: frozenset[str] = frozenset({
    "delete", "remove", "del", "clear", "purge", "drop", "truncate", "wipe",
    "erase", "send", "post", "publish", "share", "pay", "buy", "purchase",
    "transfer", "withdraw", "deposit", "cancel", "revoke", "disable",
    "uninstall", "reset", "overwrite",
})

#: Capability suffix tokens that DECLARE an agent performs a mutating / outbound
#: (destructive-class) operation. Bundled agents name capabilities by access
#: class (``{domain}.{access}``) rather than by verb — e.g. ``calendar.write``,
#: ``telegram.send`` — so a destructive action like ``delete_event`` is matched
#: against the domain's write/send-class declaration, not a literal verb match.
DESTRUCTIVE_CAPABILITY_SUFFIXES: frozenset[str] = frozenset({
    "write", "send", "delete", "remove", "notify", "post", "publish", "share",
    "manage", "clear", "purge",
})

#: Split an action string into lowercase alphanumeric tokens — handles both
#: ``{domain}.{verb}`` (``calendar.delete_event``) and ``{verb}_{noun}``
#: (``delete_event``) shapes.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _is_destructive(action: str) -> bool:
    """Return True if an action verb denotes a destructive/outward operation.

    The action is ``{domain}.{verb}`` or ``{verb}_{noun}``; a match is reported
    if any token of the action is a known destructive verb. Conservative: an
    action with no destructive token (including an empty string) is treated as
    non-destructive.

    Args:
        action: The dispatched action / tool name (e.g. ``delete_event``).

    Returns:
        True if the action is classified destructive.
    """
    tokens = set(_TOKEN_RE.findall(action.lower()))
    return bool(tokens & DESTRUCTIVE_VERBS)


class PermissionEnforcer:
    """Validates agent actions against their approved permission set.

    Agents must be registered via ``register_agent`` and their
    ``PermissionSet.user_approved`` flag must be True before any
    permission-gated RPC method is allowed.
    """

    def __init__(self) -> None:
        """Initialise the enforcer with an empty registry."""
        self._permissions: dict[str, PermissionSet] = {}
        self._capabilities: dict[str, set[str]] = {}

    def register_agent(self, agent_name: str, manifest: AgentManifest) -> None:
        """Register an agent's permission set and declared capabilities.

        The declared ``capabilities`` are the consent surface: a destructive
        ``execute:{action}`` is only permitted when the agent declared the
        matching capability (M2.1, deny-by-default).

        Args:
            agent_name: Unique agent identifier.
            manifest: Parsed AgentManifest containing the PermissionSet.
        """
        self._permissions[agent_name] = manifest.permissions
        self._capabilities[agent_name] = set(manifest.capabilities)
        logger.debug("Registered permissions for agent '%s'", agent_name)

    def _declares_destructive_action(self, agent_name: str, action: str) -> bool:
        """Return True if the agent DECLARED authority for a destructive action.

        A destructive action is considered declared when either (a) the action
        and a declared capability share a token that is itself a *destructive
        verb* (covers a literal ``{domain}.{verb}`` declaration such as
        ``calendar.delete`` ↔ ``delete_event``), or (b) the agent declares a
        capability whose suffix is a recognised destructive/mutating access
        class (``write``/``send``/``delete``/``notify``…), which is how bundled
        agents declare that they mutate or send.

        Branch (a) requires the *shared* token to be in
        :data:`DESTRUCTIVE_VERBS` rather than any shared token: a read-only
        capability shares its DOMAIN NOUN with destructive actions in the same
        domain (``email.read`` ↔ ``send_email``/``delete_email`` share
        ``"email"``), and a domain-noun overlap must NOT authorize a destructive
        action (M2.1 tightening — closes a read-only-authorizes-destructive
        false-allow).

        Args:
            agent_name: Unique agent identifier.
            action: The dispatched destructive action / tool name.

        Returns:
            True if the destructive action is covered by a declaration.
        """
        declared = self._capabilities.get(agent_name, set())
        if not declared:
            return False
        action_tokens = set(_TOKEN_RE.findall(action.lower()))
        for cap in declared:
            cap_tokens = _TOKEN_RE.findall(cap.lower())
            if not cap_tokens:
                continue
            # (a) action and capability share a token that is a destructive
            # verb (a literal verb-class declaration, e.g. ``calendar.delete``).
            # A shared domain noun (``email`` in ``email.read`` ↔ ``send_email``)
            # is NOT sufficient — only a shared destructive verb authorizes.
            if action_tokens & set(cap_tokens) & DESTRUCTIVE_VERBS:
                return True
            # (b) the capability's access-class suffix is destructive-class.
            # NOTE (intentional access-class granularity): bundled agents declare
            # mutation by access class (``calendar.write``, ``telegram.send``),
            # and the action string carries no domain (``delete_event`` shares no
            # token with ``calendar.write``). So ONE mutating-class capability
            # authorizes EVERY destructive verb for that agent — a known
            # cross-domain blanket grant accepted as the inherent coarseness of
            # access-class declarations (all 18 bundled agents rely on it). A
            # domain-scoped check here would break the legitimate
            # ``calendar.write → delete_event`` mapping. FOLLOW-UP: tighten via
            # per-action capability declarations (e.g. ``{domain}.{verb}`` or an
            # explicit allowed-actions list) so access can be scoped to domain.
            if cap_tokens[-1] in DESTRUCTIVE_CAPABILITY_SUFFIXES:
                return True
        return False

    def can_execute(self, agent_name: str, rpc_method: str) -> bool:
        """Check whether an agent is allowed to call an RPC method.

        For ``execute:{action}`` methods the check is declaration-scoped and
        deny-by-default: a destructive action is permitted only when the agent
        declared the matching capability AND is user-approved; non-destructive
        actions keep prior behaviour (allowed when approved). A bare
        ``"execute"`` (no action) is denied — an unspecified action cannot be
        proven non-destructive. All other methods use ``METHOD_PERMISSIONS``.

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

        if rpc_method == "execute" or rpc_method.startswith("execute:"):
            action = rpc_method.split(":", 1)[1] if ":" in rpc_method else ""
            if not action:
                # Defensive: unspecified action — cannot prove non-destructive.
                logger.warning(
                    "Agent '%s' bare 'execute' (no action) denied", agent_name,
                )
                return False
            if not _is_destructive(action):
                return True
            allowed = self._declares_destructive_action(agent_name, action)
            if not allowed:
                logger.warning(
                    "Agent '%s' denied undeclared destructive action '%s'",
                    agent_name, action,
                )
            return allowed

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
