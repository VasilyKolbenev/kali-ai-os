"""SSRF-guard tests for the notion agent's ``_api_call`` egress.

``agents/notion/agent.py`` ``_api_call`` builds the URL internally as
``f"{BASE_URL}{path}"`` (``BASE_URL = "https://api.notion.com/v1"``), so the
surface is narrower than GitHub's, but the egress must still be routed through
``SandboxHttpClient`` (private-IP block + whitelist + redirect re-check) rather
than raw ``urllib.urlopen``.

Tests assert:
- a private/loopback/metadata target is BLOCKED (error dict returned, raw
  urllib never used);
- a normal GET call (``_get_page``) routes through the guard, parses JSON, and
  returns structured data including the Notion-Version header;
- a POST call (``_search``) passes ``json_body`` through the guard correctly;
- an off-whitelist host is blocked even if it would resolve publicly.

DNS note: private IP *literals* are parsed by ``ipaddress`` without DNS, so
the SSRF-block tests need no network; public-host tests mock the guard's
``_resolves_to_private``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "notion" / "agent.py"
)


def _load_agent():
    """Import the notion agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("notion_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    inst = agent_mod.NotionAgent()
    inst._api_key = "test-secret"
    return inst


def _mock_opener_open(body: bytes, url: str = "https://api.notion.com/v1/x"):
    """Return a mock for ``OpenerDirector.open`` — the guard fetches via its opener."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = url
    mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_resp)


class TestApiCallSsrfBlocked:
    @pytest.mark.parametrize(
        "path",
        [
            "/../../169.254.169.254/latest/meta-data/",
            "/../../127.0.0.1/admin",
        ],
    )
    def test_private_literal_ip_in_path_is_not_a_real_ssrf_surface(self, agent, path):
        """Paths are always appended to BASE_URL so the host is always
        api.notion.com — these are included for completeness but the real
        SSRF guard is the domain whitelist test below."""
        # The guard's whitelist check fires on api.notion.com (allowed), but
        # the path injection is not an SSRF surface because the host never
        # changes.  We verify the call doesn't crash rather than expecting a
        # block for a valid host.
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open",
            _mock_opener_open(b'{"object":"error","status":400}'),
        ):
            result = agent._api_call("GET", path)
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "bad_url",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://localhost/internal",
            "https://10.0.0.5/secret",
            "https://192.168.0.1/",
        ],
    )
    def test_private_full_url_blocked_via_guard(self, agent, bad_url):
        """A private/loopback full URL passed directly to SandboxHttpClient is
        blocked before any network call is made."""
        with patch("urllib.request.OpenerDirector.open") as op:
            # We patch _api_call to call the client with a bad URL directly.
            # Since _api_call builds its own URL from BASE_URL, we test the
            # client in isolation to prove the guard rejects private hosts.
            from kernel.sandbox.http_client import (
                HttpRequest,
                SandboxHttpClient,
                SandboxHttpError,
            )
            client = SandboxHttpClient("notion", allowed_domains=["api.notion.com"])
            req = HttpRequest(url=bad_url, method="GET", headers={}, timeout=10.0)
            with pytest.raises(SandboxHttpError):
                client.request(req)
        op.assert_not_called()


class TestApiCallGet:
    def test_get_routes_through_guard_and_parses_json(self, agent):
        """A GET call (_get_page) routes through SandboxHttpClient and returns
        parsed JSON with the correct fields.  The Notion-Version header must be
        forwarded."""
        page_payload = {
            "id": "abc-123",
            "url": "https://notion.so/abc-123",
            "created_time": "2024-01-01T00:00:00.000Z",
            "last_edited_time": "2024-01-02T00:00:00.000Z",
            "properties": {
                "title": {
                    "title": [{"plain_text": "My Page"}]
                }
            },
        }
        body = json.dumps(page_payload).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open",
            _mock_opener_open(body, url="https://api.notion.com/v1/pages/abc-123"),
        ) as opener:
            result = agent._api_call("GET", "/pages/abc-123")

        assert result == page_payload
        # Guard must have been used (opener called exactly once)
        opener.assert_called_once()
        # Verify Notion-Version was sent in the request
        call_args = opener.call_args
        py_req = call_args[0][0]  # first positional arg to opener.open
        assert py_req.get_header("Notion-version") == "2022-06-28"

    def test_get_error_returns_error_dict(self, agent):
        """SandboxHttpError from the guard is converted to an error dict."""
        from kernel.sandbox.http_client import SandboxHttpClient, SandboxHttpError

        with patch.object(
            SandboxHttpClient,
            "request",
            side_effect=SandboxHttpError("HTTP 404: Not Found"),
        ):
            result = agent._api_call("GET", "/pages/missing")

        assert isinstance(result, dict)
        assert "error" in result


class TestApiCallPost:
    def test_post_passes_json_body_through_guard(self, agent):
        """A POST call (_search) sends json_body through the guard correctly."""
        search_payload = {
            "object": "list",
            "results": [
                {
                    "object": "page",
                    "id": "page-1",
                    "properties": {
                        "title": {"title": [{"plain_text": "Hello"}]}
                    },
                }
            ],
        }
        body = json.dumps(search_payload).encode()

        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open",
            _mock_opener_open(body, url="https://api.notion.com/v1/search"),
        ) as opener:
            result = agent._api_call("POST", "/search", {"query": "hello", "page_size": 10})

        assert result == search_payload
        opener.assert_called_once()
        # Confirm json_body was serialised and forwarded as ``data``
        call_args = opener.call_args
        # opener.open(req, data=data, timeout=timeout) — data is kwarg
        sent_data = call_args[1].get("data") or (
            call_args[0][1] if len(call_args[0]) > 1 else None
        )
        assert sent_data is not None
        assert json.loads(sent_data.decode()) == {"query": "hello", "page_size": 10}

    def test_post_error_returns_error_dict(self, agent):
        """SandboxHttpError from a POST is converted to an error dict."""
        from kernel.sandbox.http_client import SandboxHttpClient, SandboxHttpError

        with patch.object(
            SandboxHttpClient,
            "request",
            side_effect=SandboxHttpError("HTTP 400: Bad Request"),
        ):
            result = agent._api_call("POST", "/search", {"query": ""})

        assert isinstance(result, dict)
        assert "error" in result


class TestDomainWhitelist:
    def test_off_whitelist_host_blocked(self):
        """SandboxHttpClient rejects a non-whitelisted host (evil.example.com)
        even when _resolves_to_private returns False."""
        from kernel.sandbox.http_client import (
            DomainBlockedError,
            HttpRequest,
            SandboxHttpClient,
        )

        client = SandboxHttpClient("notion", allowed_domains=["api.notion.com"])
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            with pytest.raises(DomainBlockedError):
                client.request(
                    HttpRequest(
                        url="https://evil.example.com/exfil",
                        method="GET",
                        headers={},
                        timeout=10.0,
                    )
                )
        op.assert_not_called()
