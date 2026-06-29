"""SSRF-guard tests for the news agent's ``_api_call`` egress.

``agents/news/agent.py`` ``_api_call`` builds a URL from ``BASE_URL`` (a
compile-time constant ``https://newsapi.org/v2``) plus a caller-supplied
``path``, so the SSRF surface is narrower than the github agent; however the
HTTP egress must still route through ``SandboxHttpClient`` (private-IP block +
whitelist + redirect re-check) rather than raw ``urllib.urlopen``:

- a private/loopback/metadata host is BLOCKED (no fetch, error dict returned);
- a normal ``newsapi.org`` call routes through the guard and returns parsed JSON;
- an off-whitelist full URL is blocked even if it would resolve publicly.

DNS note: private IP *literals* are parsed by ``ipaddress`` without any DNS, so
the SSRF-block tests need no network; the public-host tests mock the guard's
``_resolves_to_private`` (real public hosts resolve to a captive address here).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "news" / "agent.py"
)


def _load_agent():
    """Import the news agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("news_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    inst = agent_mod.NewsAgent()
    inst._api_key = "test-api-key"
    return inst


def _mock_opener_open(body: bytes, url: str = "https://newsapi.org/v2/top-headlines"):
    """Mock for ``OpenerDirector.open`` — the guard fetches via its opener."""
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
        "host_url",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://localhost/internal",
            "https://10.0.0.5/secret",
            "https://192.168.0.1/",
        ],
    )
    def test_private_host_blocked(self, agent, host_url):
        """A private/loopback/metadata host injected via params is blocked."""
        with patch("urllib.request.OpenerDirector.open") as op:
            # The news agent always prepends BASE_URL, so the SSRF surface is
            # the domain whitelist check: newsapi.org-only rule blocks any
            # non-newsapi.org host. Verify with a direct SandboxHttpClient path
            # by patching the client inside _api_call to receive a bad URL.
            from kernel.sandbox.http_client import SandboxHttpClient, HttpRequest

            original_request = SandboxHttpClient.request

            def patched_request(self_inner, req: HttpRequest):
                # Replace the URL with the private host to simulate injection.
                bad_req = HttpRequest(
                    url=host_url,
                    method=req.method,
                    params=req.params,
                    headers=req.headers,
                    timeout=req.timeout,
                )
                return original_request(self_inner, bad_req)

            with patch.object(SandboxHttpClient, "request", patched_request):
                result = agent._api_call("/top-headlines", {"country": "ru"})

        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()


class TestApiCallNormalPath:
    def test_normal_call_routes_through_guard_and_parses(self, agent):
        """A normal ``/top-headlines`` call routes through the guard, parses JSON."""
        body = json.dumps({
            "status": "ok",
            "articles": [{"title": "Test", "description": "Desc",
                          "source": {"name": "BBC"}, "url": "https://bbc.com",
                          "publishedAt": "2026-01-01T00:00:00Z"}],
        }).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ):
            result = agent._api_call("/top-headlines", {"country": "ru", "pageSize": "10"})

        assert isinstance(result, dict)
        assert result.get("status") == "ok"
        assert len(result.get("articles", [])) == 1

    def test_apikey_included_in_request(self, agent):
        """The apiKey param is forwarded to the guard (appears in resolved URL)."""
        captured: list[str] = []
        body = json.dumps({"status": "ok", "articles": []}).encode()

        original_request = __import__(
            "kernel.sandbox.http_client", fromlist=["SandboxHttpClient"]
        ).SandboxHttpClient.request

        def capturing_request(self_inner, req):
            captured.append(req.resolved_url)
            return original_request(self_inner, req)

        from kernel.sandbox.http_client import SandboxHttpClient

        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ), patch.object(SandboxHttpClient, "request", capturing_request):
            agent._api_call("/top-headlines", {"country": "ru"})

        assert captured, "request() was never called — guard bypassed"
        assert "apiKey=test-api-key" in captured[0]
        assert "newsapi.org" in captured[0]


class TestApiCallOffWhitelistBlocked:
    def test_non_newsapi_host_blocked(self, agent):
        """An off-whitelist host is blocked even if it would resolve publicly."""
        from kernel.sandbox.http_client import SandboxHttpClient, HttpRequest

        original_request = SandboxHttpClient.request

        def patched_request(self_inner, req: HttpRequest):
            evil_req = HttpRequest(
                url="https://evil.example.com/exfil",
                method=req.method,
                params=req.params,
                headers=req.headers,
                timeout=req.timeout,
            )
            return original_request(self_inner, evil_req)

        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            with patch.object(SandboxHttpClient, "request", patched_request):
                result = agent._api_call("/top-headlines", {"country": "ru"})

        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()
