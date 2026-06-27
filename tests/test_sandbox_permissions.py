"""Tests for the structured permission model and PermissionEnforcer."""

import pytest
from datetime import UTC, datetime

from kernel.models import (
    AgentManifest,
    PermissionGrant,
    PermissionSet,
    VALID_PERMISSIONS,
)
from kernel.sandbox.permission_enforcer import PermissionEnforcer


class TestPermissionModel:
    def test_grant_basic(self) -> None:
        grant = PermissionGrant(name="network")
        assert grant.name == "network"
        assert grant.params == {}

    def test_grant_with_params(self) -> None:
        grant = PermissionGrant(name="network", params={"domains": ["api.example.com"]})
        assert grant.params["domains"] == ["api.example.com"]

    def test_grant_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Permission must be one of"):
            PermissionGrant(name="sudo")

    def test_permission_set_default_empty(self) -> None:
        ps = PermissionSet()
        assert ps.grants == []
        assert ps.user_approved is False
        assert ps.approval_timestamp is None

    def test_permission_set_has(self) -> None:
        ps = PermissionSet(grants=[PermissionGrant(name="storage"), PermissionGrant(name="network")])
        assert ps.has("storage") is True
        assert ps.has("network") is True
        assert ps.has("system") is False

    def test_permission_set_get_params(self) -> None:
        grant = PermissionGrant(name="network", params={"domains": ["*.example.com"]})
        ps = PermissionSet(grants=[grant])
        assert ps.get_params("network") == {"domains": ["*.example.com"]}
        assert ps.get_params("storage") == {}

    def test_manifest_structured_permission_set(self) -> None:
        manifest = AgentManifest(
            name="agent-x",
            version="1.0.0",
            description="Test",
            permissions=PermissionSet(
                grants=[PermissionGrant(name="network", params={"domains": ["api.test.com"]})],
                user_approved=True,
                approval_timestamp=datetime(2026, 4, 13, tzinfo=UTC),
            ),
        )
        assert manifest.permissions.has("network")
        assert manifest.permissions.user_approved is True
        assert manifest.permissions.get_params("network") == {"domains": ["api.test.com"]}

    def test_manifest_backward_compat_flat_list(self) -> None:
        manifest = AgentManifest(
            name="legacy",
            version="0.1.0",
            description="Legacy agent",
            permissions=["storage", "network"],
        )
        assert isinstance(manifest.permissions, PermissionSet)
        assert manifest.permissions.has("storage")
        assert manifest.permissions.has("network")
        assert manifest.permissions.user_approved is False

    def test_manifest_backward_compat_unknown_permissions_skipped(self) -> None:
        # Unknown permissions are silently skipped (backward compat)
        manifest = AgentManifest(
            name="old-agent",
            version="0.1.0",
            description="Old agent with unknown perms",
            permissions=["storage", "legacy_perm", "another_unknown"],
        )
        assert manifest.permissions.has("storage")
        assert not manifest.permissions.has("legacy_perm")
        assert not manifest.permissions.has("another_unknown")

    def test_manifest_backward_compat_dict_in_list(self) -> None:
        manifest = AgentManifest(
            name="agent-y",
            version="1.0.0",
            description="Agent with dict permissions",
            permissions=[{"name": "network", "params": {"domains": ["api.test.com"]}}],
        )
        assert manifest.permissions.has("network")
        assert manifest.permissions.get_params("network") == {"domains": ["api.test.com"]}

    def test_manifest_empty_flat_list(self) -> None:
        manifest = AgentManifest(
            name="minimal",
            version="1.0.0",
            description="Minimal agent",
            permissions=[],
        )
        assert isinstance(manifest.permissions, PermissionSet)
        assert manifest.permissions.grants == []


class TestPermissionEnforcer:
    def _make_approved_manifest(self, *permission_names: str) -> AgentManifest:
        grants = [PermissionGrant(name=n) for n in permission_names]
        return AgentManifest(
            name="agent",
            version="1.0.0",
            description="Test",
            permissions=PermissionSet(grants=grants, user_approved=True),
        )

    def _make_unapproved_manifest(self, *permission_names: str) -> AgentManifest:
        grants = [PermissionGrant(name=n) for n in permission_names]
        return AgentManifest(
            name="agent",
            version="1.0.0",
            description="Test",
            permissions=PermissionSet(grants=grants, user_approved=False),
        )

    def test_approved_agent_allowed(self) -> None:
        enforcer = PermissionEnforcer()
        manifest = self._make_approved_manifest("network")
        enforcer.register_agent("net-agent", manifest)
        assert enforcer.can_execute("net-agent", "network.request") is True

    def test_unapproved_agent_blocked(self) -> None:
        enforcer = PermissionEnforcer()
        manifest = self._make_unapproved_manifest("network")
        enforcer.register_agent("net-agent", manifest)
        assert enforcer.can_execute("net-agent", "network.request") is False

    def test_missing_permission_blocked(self) -> None:
        enforcer = PermissionEnforcer()
        # Agent only has storage, not network
        manifest = self._make_approved_manifest("storage")
        enforcer.register_agent("store-agent", manifest)
        assert enforcer.can_execute("store-agent", "network.request") is False

    def test_unregistered_agent_blocked(self) -> None:
        enforcer = PermissionEnforcer()
        assert enforcer.can_execute("ghost-agent", "network.request") is False

    def test_unknown_rpc_method_allowed_when_approved(self) -> None:
        # Methods not in METHOD_PERMISSIONS have no required permission
        enforcer = PermissionEnforcer()
        manifest = self._make_approved_manifest("storage")
        enforcer.register_agent("store-agent", manifest)
        assert enforcer.can_execute("store-agent", "some.unknown.method") is True

    def test_get_network_domains_returns_params(self) -> None:
        enforcer = PermissionEnforcer()
        manifest = AgentManifest(
            name="agent",
            version="1.0.0",
            description="Test",
            permissions=PermissionSet(
                grants=[PermissionGrant(name="network", params={"domains": ["api.example.com"]})],
                user_approved=True,
            ),
        )
        enforcer.register_agent("net-agent", manifest)
        assert enforcer.get_network_domains("net-agent") == ["api.example.com"]

    def test_get_network_domains_unregistered_returns_empty(self) -> None:
        enforcer = PermissionEnforcer()
        assert enforcer.get_network_domains("ghost") == []

    def test_all_method_permissions_enforced(self) -> None:
        from kernel.sandbox.permission_enforcer import METHOD_PERMISSIONS

        enforcer = PermissionEnforcer()
        # Agent with all permissions approved
        all_perms = list(VALID_PERMISSIONS)
        grants = [PermissionGrant(name=n) for n in all_perms]
        manifest = AgentManifest(
            name="super",
            version="1.0.0",
            description="Super agent",
            permissions=PermissionSet(grants=grants, user_approved=True),
        )
        enforcer.register_agent("super-agent", manifest)
        for method in METHOD_PERMISSIONS:
            assert enforcer.can_execute("super-agent", method) is True


class TestIsDestructive:
    """Unit cases for the destructive-action classifier (M2.1)."""

    @pytest.mark.parametrize(
        "action",
        [
            "delete_event",
            "delete_task",
            "send_message",
            "send_email",
            "send_notification",
            "calendar.delete_event",
            "telegram.send",
            "clear_canvas",
            "remove_item",
            "purge_logs",
            "cancel_order",
            "revoke_token",
            "transfer_funds",
            "uninstall_plugin",
            "overwrite_file",
            "reset_device",
            "publish_post",
            "share_reel",
        ],
    )
    def test_destructive_actions_flagged(self, action: str) -> None:
        from kernel.sandbox.permission_enforcer import _is_destructive

        assert _is_destructive(action) is True, action

    @pytest.mark.parametrize(
        "action",
        [
            "get_events",
            "get_weather",
            "list_tasks",
            "create_event",
            "add_task",
            "complete_task",
            "log_water",
            "read_messages",
            "check_inbox",
            "search_emails",
            "get_summary",
            "render_widget",
            "update_profile",  # update-own is non-destructive per policy
            "control_device",  # 'control' not a destructive token
        ],
    )
    def test_non_destructive_actions_not_flagged(self, action: str) -> None:
        from kernel.sandbox.permission_enforcer import _is_destructive

        assert _is_destructive(action) is False, action

    def test_empty_action_not_destructive_token(self) -> None:
        # An empty/no-verb string carries no destructive token. (The bare
        # "execute" guard is enforced separately in can_execute.)
        from kernel.sandbox.permission_enforcer import _is_destructive

        assert _is_destructive("") is False


class TestDeclarationScopedExecute:
    """M2.1: execute:{action} is declaration-scoped + deny-by-default."""

    def _agent(
        self, *, capabilities: list[str], approved: bool = True
    ) -> AgentManifest:
        return AgentManifest(
            name="agent",
            version="1.0.0",
            description="Test",
            capabilities=capabilities,
            permissions=PermissionSet(grants=[], user_approved=approved),
        )

    def test_destructive_declared_allowed(self) -> None:
        # calendar declares calendar.write → delete_event (destructive) allowed.
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "calendar", self._agent(capabilities=["calendar.read", "calendar.write"])
        )
        assert enforcer.can_execute("calendar", "execute:delete_event") is True

    def test_destructive_send_declared_allowed(self) -> None:
        # telegram declares telegram.send → send_message (destructive) allowed.
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "telegram", self._agent(capabilities=["telegram.send", "telegram.notify"])
        )
        assert enforcer.can_execute("telegram", "execute:send_message") is True

    def test_destructive_undeclared_denied(self) -> None:
        # THE CORE FIX: agent declares only read-class caps but tries a
        # destructive delete → DENIED even though user_approved.
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "reader", self._agent(capabilities=["calendar.read"])
        )
        assert enforcer.can_execute("reader", "execute:delete_event") is False

    def test_destructive_no_capabilities_denied(self) -> None:
        # Approved agent with NO declared capabilities cannot do destructive.
        enforcer = PermissionEnforcer()
        enforcer.register_agent("bare", self._agent(capabilities=[]))
        assert enforcer.can_execute("bare", "execute:send_email") is False

    def test_non_destructive_allowed_when_approved(self) -> None:
        # Non-destructive action keeps current behavior: allowed when approved,
        # regardless of declared capabilities.
        enforcer = PermissionEnforcer()
        enforcer.register_agent("weather", self._agent(capabilities=[]))
        assert enforcer.can_execute("weather", "execute:get_weather") is True

    def test_non_destructive_denied_when_unapproved(self) -> None:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "weather", self._agent(capabilities=["weather.current"], approved=False)
        )
        assert enforcer.can_execute("weather", "execute:get_weather") is False

    def test_destructive_denied_when_unapproved(self) -> None:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "calendar",
            self._agent(capabilities=["calendar.write"], approved=False),
        )
        assert enforcer.can_execute("calendar", "execute:delete_event") is False

    def test_unregistered_agent_execute_denied(self) -> None:
        enforcer = PermissionEnforcer()
        assert enforcer.can_execute("ghost", "execute:get_weather") is False

    def test_bare_execute_denied(self) -> None:
        # Defensive: an unspecified action ("execute" with no ":action") can't
        # be proven non-destructive → deny.
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "calendar", self._agent(capabilities=["calendar.write"])
        )
        assert enforcer.can_execute("calendar", "execute") is False

    def test_existing_method_permission_logic_unchanged(self) -> None:
        # network.request still routed through METHOD_PERMISSIONS, not the
        # execute: branch.
        enforcer = PermissionEnforcer()
        manifest = AgentManifest(
            name="agent",
            version="1.0.0",
            description="Test",
            capabilities=["telegram.send"],
            permissions=PermissionSet(
                grants=[PermissionGrant(name="network")], user_approved=True
            ),
        )
        enforcer.register_agent("net", manifest)
        assert enforcer.can_execute("net", "network.request") is True
        # Without the network grant, network.request denied even if approved.
        enforcer.register_agent("nonet", self._agent(capabilities=["telegram.send"]))
        assert enforcer.can_execute("nonet", "network.request") is False


class TestDestructiveDeclarationOvergrant:
    """M2.1 tightening: a shared DOMAIN-NOUN token must not authorize a
    destructive action through branch (a). Only a shared *destructive verb*
    (or a mutating access-class suffix via branch (b)) authorizes."""

    def _agent(self, *, capabilities: list[str]) -> AgentManifest:
        return AgentManifest(
            name="agent",
            version="1.0.0",
            description="Test",
            capabilities=capabilities,
            permissions=PermissionSet(grants=[], user_approved=True),
        )

    def test_read_only_cap_does_not_authorize_send_via_domain_noun(self) -> None:
        # THE FALSE-ALLOW being closed: email.read (read-only) shares only the
        # domain noun "email" with send_email — must NOT authorize it.
        enforcer = PermissionEnforcer()
        enforcer.register_agent("reader", self._agent(capabilities=["email.read"]))
        assert enforcer.can_execute("reader", "execute:send_email") is False

    def test_read_only_cap_does_not_authorize_delete_via_domain_noun(self) -> None:
        # email.read shares "email" with delete_email — still must NOT authorize.
        enforcer = PermissionEnforcer()
        enforcer.register_agent("reader", self._agent(capabilities=["email.read"]))
        assert enforcer.can_execute("reader", "execute:delete_email") is False

    def test_calendar_read_does_not_authorize_delete_event(self) -> None:
        # Already correct (calendar.read shares no token with delete_event) —
        # lock it so the tightening cannot regress it.
        enforcer = PermissionEnforcer()
        enforcer.register_agent("reader", self._agent(capabilities=["calendar.read"]))
        assert enforcer.can_execute("reader", "execute:delete_event") is False

    def test_literal_destructive_verb_match_allowed_via_branch_a(self) -> None:
        # Branch (a) still authorizes when the shared token IS a destructive
        # verb: calendar.delete ↔ delete_event share "delete" ∈ DESTRUCTIVE_VERBS.
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "cal", self._agent(capabilities=["calendar.delete"])
        )
        assert enforcer.can_execute("cal", "execute:delete_event") is True

    # --- Regression locks: legitimate mutating access-class mappings that go
    # --- through branch (b) and MUST remain allowed (18-agent invariants).
    def test_calendar_write_allows_delete_event(self) -> None:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "cal", self._agent(capabilities=["calendar.read", "calendar.write"])
        )
        assert enforcer.can_execute("cal", "execute:delete_event") is True

    def test_telegram_send_allows_send_message(self) -> None:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "tg", self._agent(capabilities=["telegram.send", "telegram.notify"])
        )
        assert enforcer.can_execute("tg", "execute:send_message") is True

    def test_email_send_allows_send_email(self) -> None:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "mail",
            self._agent(capabilities=["email.read", "email.send", "email.search"]),
        )
        assert enforcer.can_execute("mail", "execute:send_email") is True

    def test_tasks_write_allows_delete_task(self) -> None:
        enforcer = PermissionEnforcer()
        enforcer.register_agent(
            "tasks", self._agent(capabilities=["tasks.read", "tasks.write"])
        )
        assert enforcer.can_execute("tasks", "execute:delete_task") is True
