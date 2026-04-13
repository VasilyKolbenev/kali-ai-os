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
