"""Tests for the NetworkProxy sandbox component."""

import pytest
from unittest.mock import MagicMock, patch

from kernel.sandbox.network_proxy import NetworkProxy


class TestNetworkProxy:
    def test_domain_allowed_exact(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["api.example.com"])
        assert proxy.is_domain_allowed("agent-a", "api.example.com") is True

    def test_domain_blocked_not_in_whitelist(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["api.example.com"])
        assert proxy.is_domain_allowed("agent-a", "evil.com") is False

    def test_domain_wildcard_match(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["*.example.com"])
        assert proxy.is_domain_allowed("agent-a", "sub.example.com") is True
        assert proxy.is_domain_allowed("agent-a", "api.example.com") is True
        assert proxy.is_domain_allowed("agent-a", "example.com") is False

    def test_unregistered_agent_no_domains(self) -> None:
        proxy = NetworkProxy()
        assert proxy.is_domain_allowed("ghost-agent", "example.com") is False

    async def test_missing_url_returns_error(self) -> None:
        proxy = NetworkProxy()
        result = await proxy.handle("agent-a", {})
        assert "error" in result
        assert result["error"] == "URL is required"

    async def test_blocked_domain_handle_returns_error(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["allowed.com"])
        result = await proxy.handle("agent-a", {"url": "https://blocked.com/api"})
        assert "error" in result
        assert "Blocked" in result["error"]

    async def test_rate_limited_handle_returns_error(self) -> None:
        proxy = NetworkProxy(max_requests_per_min=2)
        proxy.set_allowed_domains("agent-a", ["example.com"])

        # Exhaust the rate limit
        proxy._rate_limiter.check("agent-a")
        proxy._rate_limiter.check("agent-a")

        result = await proxy.handle("agent-a", {"url": "https://example.com/api"})
        assert result == {"error": "Rate limit exceeded"}

    async def test_successful_request(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["example.com"])

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = await proxy.handle("agent-a", {"url": "https://example.com/api"})

        assert result["status"] == 200
        assert '{"ok": true}' in result["body"]

    async def test_request_exception_returns_error(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["example.com"])

        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = await proxy.handle("agent-a", {"url": "https://example.com/api"})

        assert "error" in result
        assert "connection refused" in result["error"]

    def test_domain_match_case_insensitive(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["API.Example.COM"])
        assert proxy.is_domain_allowed("agent-a", "api.example.com") is True

    def test_extract_domain(self) -> None:
        assert NetworkProxy._extract_domain("https://api.example.com/path?q=1") == "api.example.com"
        assert NetworkProxy._extract_domain("http://localhost:8000/test") == "localhost"
        assert NetworkProxy._extract_domain("not-a-url") == ""

    async def test_timeout_capped_at_30(self) -> None:
        proxy = NetworkProxy()
        proxy.set_allowed_domains("agent-a", ["example.com"])

        captured_timeout: list[int] = []

        def fake_urlopen(req: object, data: object, timeout: int) -> None:
            captured_timeout.append(timeout)
            raise OSError("captured")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            await proxy.handle("agent-a", {"url": "https://example.com/", "timeout": 999})

        assert captured_timeout[0] == 30
