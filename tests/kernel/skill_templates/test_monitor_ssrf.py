"""SSRF-guard tests for the monitor skill template (WS-2 Task 2.8).

The monitor template fetches a USER/VOICE-supplied URL, so it is the
third-party-reachable SSRF path. These tests assert that its network egress
goes through ``SandboxHttpClient`` (private-IP block + whitelist + redirect
re-check + rate limit) rather than raw ``urllib.urlopen``:

- a request whose host resolves to a private/loopback/link-local address
  (``127.0.0.1``, ``169.254.169.254``, RFC1918) is BLOCKED — recorded as a
  failed check (``status_code is None`` + ``error``), never fetched;
- a whitelisted/public host is allowed (the guard + http layer are mocked so
  the check does not depend on real DNS, which is captive in CI);
- the per-agent rate limit is honored.

DNS note: real public hosts resolve to a captive/private address in this
sandbox, so public-host tests mock ``_resolves_to_private``; SSRF-block tests
use private IP *literals*, which ``ipaddress`` parses without any DNS lookup.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kernel.skill_templates.monitor import MonitorTemplate


def _mock_opener_open(status: int = 200) -> MagicMock:
    """Mock for ``OpenerDirector.open`` — the guard fetches via a built opener.

    Patching ``urllib.request.urlopen`` does NOT intercept the guard, which
    uses ``build_opener(...).open(...)``; so the opener's ``open`` is patched.
    """
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.url = "https://status.example.com/"
    mock_resp.headers.items.return_value = [("Content-Type", "text/plain")]
    mock_resp.read.return_value = b"ok"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_resp)


@pytest.fixture
def template(tmp_path) -> MonitorTemplate:
    return MonitorTemplate(skill_name="api-health", data_dir=tmp_path)


class TestMonitorSsrfBlocked:
    """A voice-built monitor MUST NOT be able to hit internal infrastructure."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1:8080/admin",               # loopback
            "http://localhost/secret",                   # loopback name
            "http://10.0.0.5/internal",                  # RFC1918
            "http://192.168.1.1/router",                 # RFC1918
            "http://172.16.0.9/db",                      # RFC1918
        ],
    )
    async def test_private_target_blocked(self, template, url):
        """Egress to a private/loopback/link-local host is blocked (SSRF).

        The block is recorded as a failed check (``status_code is None`` with an
        ``error``) and the network is NEVER reached. Private IP *literals* need
        no DNS, so the real ``_resolves_to_private`` rejects them offline.
        """
        config = {"url": url, "expected_status": 200}
        with patch("urllib.request.OpenerDirector.open") as op:
            result = await template.execute("check", {}, config)
        assert result["status_code"] is None
        assert result["is_ok"] is False
        # The guard rejected before any real fetch.
        op.assert_not_called()
        hist = await template.execute("history", {}, config)
        assert hist["fail_count"] == 1
        assert hist["history"][-1].get("error")


class TestMonitorPublicAllowed:
    """A normal public health check still works through the guard."""

    @pytest.mark.asyncio
    async def test_public_host_allowed(self, template):
        config = {"url": "https://status.example.com/health", "expected_status": 200}
        # Public host resolves to a captive address in CI → force "not private".
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(status=200)
        ):
            result = await template.execute("check", {}, config)
        assert result["status_code"] == 200
        assert result["is_ok"] is True

    @pytest.mark.asyncio
    async def test_public_host_non_200_recorded(self, template):
        config = {"url": "https://status.example.com/health", "expected_status": 200}
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(status=503)
        ):
            result = await template.execute("check", {}, config)
        assert result["status_code"] == 503
        assert result["is_ok"] is False


class TestMonitorGoesThroughGuard:
    """Egress must flow through SandboxHttpClient, not raw urllib."""

    @pytest.mark.asyncio
    async def test_uses_sandbox_http_client(self, template):
        """The guarded client's ``request`` is invoked for a check."""
        config = {"url": "https://status.example.com/", "expected_status": 200}
        with patch(
            "kernel.skill_templates.monitor.SandboxHttpClient"
        ) as cls:
            instance = cls.return_value
            resp = MagicMock()
            resp.status = 200
            instance.request.return_value = resp
            await template.execute("check", {}, config)
        instance.request.assert_called_once()


class TestMonitorRateLimit:
    """The per-agent rate limit is honored when a limiter is configured."""

    @pytest.mark.asyncio
    async def test_rate_limit_blocks(self, template):
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=False)
        template._rate_limiter = limiter
        config = {"url": "https://status.example.com/", "expected_status": 200}
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            result = await template.execute("check", {}, config)
        # Rate-limited → recorded as a failed check, no real fetch.
        assert result["status_code"] is None
        assert result["is_ok"] is False
        op.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_allows(self, template):
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=True)
        template._rate_limiter = limiter
        config = {"url": "https://status.example.com/", "expected_status": 200}
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(status=200)
        ):
            result = await template.execute("check", {}, config)
        assert result["status_code"] == 200
        limiter.check.assert_called_once_with("api-health")


class TestMonitorMockStillWorks:
    """The existing ``_mock_status`` test hook is preserved (no network)."""

    @pytest.mark.asyncio
    async def test_mock_status_bypasses_network(self, template, monkeypatch):
        monkeypatch.setenv("KALI_TESTING", "1")
        config = {"url": "https://status.example.com/", "expected_status": 200}
        with patch("urllib.request.urlopen") as uo:
            result = await template.execute("check", {"_mock_status": 200}, config)
        assert result["status_code"] == 200
        assert result["is_ok"] is True
        uo.assert_not_called()
