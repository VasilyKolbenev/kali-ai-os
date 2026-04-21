"""Tests for SandboxBackend (InProcessSandbox)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kernel.sandbox.backend import (
    DispatchRequest,
    DispatchResult,
    InProcessSandbox,
    SandboxBackend,
)


def _make_runtime(return_value=None, raise_exc=None):
    runtime = MagicMock()
    if raise_exc is not None:
        runtime.dispatch = AsyncMock(side_effect=raise_exc)
    else:
        runtime.dispatch = AsyncMock(return_value=return_value or {"result": "ok"})
    return runtime


class TestBasicDispatch:
    async def test_successful_dispatch(self):
        runtime = _make_runtime(return_value={"temp_c": 8})
        sandbox = InProcessSandbox(agent_runtime=runtime)

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="weather", action="get_now"),
        )

        assert result.ok is True
        assert result.result == {"temp_c": 8}
        assert result.backend == "in_process"
        assert result.duration_ms >= 0
        runtime.dispatch.assert_awaited_once_with("weather", "get_now", {})

    async def test_non_dict_result_wrapped(self):
        runtime = _make_runtime(return_value="string-result")
        sandbox = InProcessSandbox(agent_runtime=runtime)

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is True
        assert result.result == {"result": "string-result"}

    async def test_exception_becomes_error(self):
        runtime = _make_runtime(raise_exc=RuntimeError("boom"))
        sandbox = InProcessSandbox(agent_runtime=runtime)

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is False
        assert "boom" in (result.error or "")

    def test_protocol_conformance(self):
        runtime = _make_runtime()
        sandbox = InProcessSandbox(agent_runtime=runtime)
        assert isinstance(sandbox, SandboxBackend)


class TestRateLimit:
    async def test_blocks_when_exceeded(self):
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=False)
        runtime = _make_runtime()
        sandbox = InProcessSandbox(
            agent_runtime=runtime, rate_limiter=limiter,
        )

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is False
        assert result.denied_reason == "rate_limit"
        runtime.dispatch.assert_not_awaited()

    async def test_allows_when_under_limit(self):
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=True)
        runtime = _make_runtime(return_value={"ok": True})
        sandbox = InProcessSandbox(
            agent_runtime=runtime, rate_limiter=limiter,
        )

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is True
        limiter.check.assert_called_once_with("x")


class TestPermissionEnforcer:
    async def test_unregistered_agent_passes(self):
        """Unregistered agent (not in enforcer._permissions) → allowed (built-ins)."""
        enforcer = MagicMock()
        enforcer._permissions = {}  # agent not registered
        enforcer.can_execute = MagicMock(return_value=False)
        runtime = _make_runtime()
        sandbox = InProcessSandbox(agent_runtime=runtime, enforcer=enforcer)

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is True  # unregistered → bypass (allows built-ins)

    async def test_registered_and_denied(self):
        enforcer = MagicMock()
        enforcer._permissions = {"x": object()}  # registered
        enforcer.can_execute = MagicMock(return_value=False)
        runtime = _make_runtime()
        sandbox = InProcessSandbox(agent_runtime=runtime, enforcer=enforcer)

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is False
        assert result.denied_reason == "permission"
        runtime.dispatch.assert_not_awaited()

    async def test_registered_and_allowed(self):
        enforcer = MagicMock()
        enforcer._permissions = {"x": object()}
        enforcer.can_execute = MagicMock(return_value=True)
        runtime = _make_runtime(return_value={"data": 1})
        sandbox = InProcessSandbox(agent_runtime=runtime, enforcer=enforcer)

        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is True


class TestAuditSink:
    async def test_ok_dispatch_writes_record(self):
        records: list = []
        runtime = _make_runtime(return_value={"ok": 1})
        sandbox = InProcessSandbox(
            agent_runtime=runtime, audit_sink=records.append,
        )
        await sandbox.dispatch(
            DispatchRequest(agent_name="a", action="b", request_id="req-1"),
        )

        assert len(records) == 1
        assert records[0]["agent"] == "a"
        assert records[0]["action"] == "b"
        assert records[0]["status"] == "ok"
        assert records[0]["request_id"] == "req-1"
        assert records[0]["duration_ms"] >= 0

    async def test_rate_limit_denial_logged(self):
        records: list = []
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=False)
        sandbox = InProcessSandbox(
            agent_runtime=_make_runtime(),
            rate_limiter=limiter,
            audit_sink=records.append,
        )
        await sandbox.dispatch(DispatchRequest(agent_name="x", action="y"))

        assert records[0]["status"] == "denied"
        assert records[0]["denied_reason"] == "rate_limit"

    async def test_error_is_logged(self):
        records: list = []
        runtime = _make_runtime(raise_exc=ValueError("bad"))
        sandbox = InProcessSandbox(
            agent_runtime=runtime, audit_sink=records.append,
        )
        await sandbox.dispatch(DispatchRequest(agent_name="x", action="y"))

        assert records[0]["status"] == "error"
        assert "bad" in records[0].get("error", "")

    async def test_audit_failure_does_not_break_dispatch(self):
        def broken_sink(record):
            raise RuntimeError("sink is broken")

        runtime = _make_runtime(return_value={"ok": 1})
        sandbox = InProcessSandbox(
            agent_runtime=runtime, audit_sink=broken_sink,
        )
        result = await sandbox.dispatch(
            DispatchRequest(agent_name="x", action="y"),
        )
        assert result.ok is True


class TestHealth:
    async def test_health_reports_capabilities(self):
        sandbox = InProcessSandbox(
            agent_runtime=_make_runtime(),
            enforcer=MagicMock(),
            rate_limiter=MagicMock(),
            audit_sink=lambda r: None,
        )
        info = await sandbox.health()
        assert info["backend"] == "in_process"
        assert info["enforcer_enabled"] is True
        assert info["rate_limiter_enabled"] is True
        assert info["audit_sink_enabled"] is True

    async def test_health_bare(self):
        sandbox = InProcessSandbox(agent_runtime=_make_runtime())
        info = await sandbox.health()
        assert info["enforcer_enabled"] is False
        assert info["rate_limiter_enabled"] is False
        assert info["audit_sink_enabled"] is False
