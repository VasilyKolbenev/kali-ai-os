"""Tests for SandboxHttpClient."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from kernel.sandbox.http_client import (
    DomainBlockedError,
    HttpRequest,
    HttpResponse,
    RateLimitError,
    SandboxHttpClient,
    SandboxHttpError,
)


def _mock_urlopen(body: bytes = b"ok", status: int = 200):
    """Return a context-manager-compatible mock for urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.url = "https://api.example.com/"
    mock_resp.headers.items.return_value = [("Content-Type", "text/plain")]
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_resp)


class TestWhitelist:
    def test_allowed_host_passes(self):
        client = SandboxHttpClient(
            "agent1", allowed_domains=["api.example.com"],
        )
        with patch("urllib.request.urlopen", _mock_urlopen()):
            resp = client.get("https://api.example.com/path")
        assert resp.status == 200

    def test_blocked_host_raises(self):
        client = SandboxHttpClient("agent1", allowed_domains=["api.example.com"])
        with pytest.raises(DomainBlockedError, match="not whitelisted"):
            client.get("https://evil.com/exfil")

    def test_empty_whitelist_blocks_all(self):
        client = SandboxHttpClient("agent1", allowed_domains=[])
        with pytest.raises(DomainBlockedError):
            client.get("https://api.example.com/")

    def test_wildcard_subdomain(self):
        client = SandboxHttpClient("agent1", allowed_domains=["*.example.com"])
        with patch("urllib.request.urlopen", _mock_urlopen()):
            client.get("https://api.example.com/")
            client.get("https://deep.sub.example.com/")
        # No raise = pass

    def test_wildcard_does_not_match_root_when_specified(self):
        client = SandboxHttpClient("agent1", allowed_domains=["*.example.com"])
        # Root domain without subdomain should not match "*.example.com"
        with pytest.raises(DomainBlockedError):
            client.get("https://example.com/")


class TestRateLimit:
    def test_limit_exceeded_raises(self):
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=False)
        client = SandboxHttpClient(
            "agent1", allowed_domains=["api.example.com"], rate_limiter=limiter,
        )
        with pytest.raises(RateLimitError):
            client.get("https://api.example.com/")

    def test_limit_ok_allows_call(self):
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=True)
        client = SandboxHttpClient(
            "agent1", allowed_domains=["api.example.com"], rate_limiter=limiter,
        )
        with patch("urllib.request.urlopen", _mock_urlopen()):
            client.get("https://api.example.com/")
        limiter.check.assert_called_once_with("agent1")


class TestResponseParsing:
    def test_get_request(self):
        client = SandboxHttpClient("a", allowed_domains=["api.example.com"])
        with patch("urllib.request.urlopen", _mock_urlopen(body=b"hello")):
            resp = client.get("https://api.example.com/")
        assert resp.status == 200
        assert resp.text == "hello"

    def test_json_helper(self):
        client = SandboxHttpClient("a", allowed_domains=["api.example.com"])
        with patch("urllib.request.urlopen", _mock_urlopen(body=b'{"x":1}')):
            resp = client.get("https://api.example.com/")
        assert resp.json() == {"x": 1}

    def test_post_with_json_body(self):
        client = SandboxHttpClient("a", allowed_domains=["api.example.com"])
        with patch("urllib.request.urlopen", _mock_urlopen(body=b"created", status=201)) as uo:
            resp = client.post("https://api.example.com/items", json={"name": "x"})
        assert resp.status == 201
        # Inspect Request object to confirm Content-Type set
        call_args = uo.call_args
        request_obj = call_args.args[0]
        assert request_obj.get_method() == "POST"
        assert request_obj.get_header("Content-type") == "application/json"


class TestParams:
    def test_query_string_encoded(self):
        client = SandboxHttpClient("a", allowed_domains=["api.example.com"])
        captured = {}

        def fake_open(req, data=None, timeout=None):
            captured["url"] = req.full_url
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.url = req.full_url
            mock_resp.headers.items.return_value = []
            mock_resp.read.return_value = b"{}"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_open):
            client.get(
                "https://api.example.com/prices",
                params={"ids": "bitcoin", "vs": "usd"},
            )

        assert "ids=bitcoin" in captured["url"]
        assert "vs=usd" in captured["url"]


class TestAuditSink:
    def test_ok_logged(self):
        records: list[dict] = []
        client = SandboxHttpClient(
            "a", allowed_domains=["api.example.com"],
            audit_sink=records.append,
        )
        with patch("urllib.request.urlopen", _mock_urlopen()):
            client.get("https://api.example.com/")
        assert len(records) == 1
        assert records[0]["agent"] == "a"
        assert records[0]["status"] == "ok"
        assert records[0]["backend"] == "http_client"

    def test_domain_block_logged(self):
        records: list[dict] = []
        client = SandboxHttpClient(
            "a", allowed_domains=[],
            audit_sink=records.append,
        )
        with pytest.raises(DomainBlockedError):
            client.get("https://blocked.com/")
        assert records[0]["status"] == "denied"
        assert records[0]["denied_reason"] == "domain_blocked"

    def test_rate_limit_logged(self):
        records: list[dict] = []
        limiter = MagicMock()
        limiter.check = MagicMock(return_value=False)
        client = SandboxHttpClient(
            "a", allowed_domains=["api.example.com"],
            rate_limiter=limiter, audit_sink=records.append,
        )
        with pytest.raises(RateLimitError):
            client.get("https://api.example.com/")
        assert records[0]["status"] == "denied"
        assert records[0]["denied_reason"] == "rate_limit"


class TestTimeoutCapped:
    def test_timeout_capped_at_30s(self):
        client = SandboxHttpClient("a", allowed_domains=["api.example.com"])
        captured = {}

        def fake_open(req, data=None, timeout=None):
            captured["timeout"] = timeout
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.url = ""
            mock_resp.headers.items.return_value = []
            mock_resp.read.return_value = b""
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_open):
            client.request(
                HttpRequest(url="https://api.example.com/", timeout=600),
            )
        assert captured["timeout"] == 30  # cap


class TestFactory:
    def test_for_agent_reads_context(self):
        enforcer = MagicMock()
        enforcer.get_network_domains = MagicMock(return_value=["api.example.com"])
        rate_limiter = MagicMock()
        audit = MagicMock()

        ctx = MagicMock()
        ctx.permission_enforcer = enforcer
        ctx.rate_limiter = rate_limiter
        ctx.audit_sink = audit

        client = SandboxHttpClient.for_agent("crypto", ctx)
        enforcer.get_network_domains.assert_called_once_with("crypto")
        assert "api.example.com" in client._allowed

    def test_for_agent_survives_missing_enforcer(self):
        ctx = MagicMock(spec=[])  # no attributes
        # Should not raise
        client = SandboxHttpClient.for_agent("x", ctx)
        assert client._allowed == []
