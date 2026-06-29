"""SSRF-guard tests for the github agent's ``_api_call`` egress.

``agents/github/agent.py`` ``_api_call`` accepts a FULL URL from the caller
(``path if path.startswith("https://") else f"{BASE_URL}{path}"``), so it is a
caller-reachable SSRF path. These tests assert that ``_api_call`` routes egress
through ``SandboxHttpClient`` (the fail-closed guard: private-IP block +
whitelist + redirect re-check) rather than raw ``urllib.urlopen``:

- a private/loopback/metadata target passed as ``path`` is BLOCKED (no fetch,
  error dict returned, raw urllib never used);
- a normal ``api.github.com`` call routes through the guard and returns parsed
  JSON;
- a caller-supplied full ``https://api.github.com/...`` URL still works and is
  guarded.

DNS note: private IP *literals* are parsed by ``ipaddress`` without any DNS, so
the SSRF-block test needs no network; the public-host tests mock the guard's
``_resolves_to_private`` (real public hosts resolve to a captive address here).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "github" / "agent.py"
)


def _load_agent():
    """Import the github agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("github_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    inst = agent_mod.GitHubAgent()
    inst._token = "test-token"
    return inst


def _mock_opener_open(body: bytes, url: str = "https://api.github.com/x"):
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
        "path",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://localhost/internal",
            "https://10.0.0.5/secret",
            "https://192.168.0.1/",
        ],
    )
    def test_private_full_url_blocked(self, agent, path):
        """A private/loopback full URL is blocked and never fetched."""
        with patch("urllib.request.OpenerDirector.open") as op:
            result = agent._api_call(path)
        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()


class TestApiCallRelativePath:
    def test_relative_path_routes_through_guard(self, agent):
        """A normal ``/user/repos`` call routes through the guard, parses JSON."""
        body = json.dumps([{"full_name": "octocat/hello"}]).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ):
            result = agent._api_call("/user/repos?sort=updated")
        assert result == [{"full_name": "octocat/hello"}]


class TestApiCallFullUrlAllowed:
    def test_github_full_url_routes_through_guard(self, agent):
        """A caller-supplied ``https://api.github.com/...`` full URL still works."""
        body = json.dumps({"full_name": "octocat/hello"}).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ):
            result = agent._api_call("https://api.github.com/repos/octocat/hello")
        assert result == {"full_name": "octocat/hello"}

    def test_non_github_full_url_blocked(self, agent):
        """A full URL to a non-whitelisted host is blocked (whitelist defaults
        to api.github.com), even if it would resolve publicly."""
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            result = agent._api_call("https://evil.example.com/exfil")
        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()
