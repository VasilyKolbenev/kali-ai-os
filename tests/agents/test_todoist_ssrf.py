"""SSRF-guard tests for the todoist agent's ``_api_call`` egress.

``agents/todoist/agent.py`` ``_api_call`` always builds the URL as
``BASE_URL + path`` where ``BASE_URL = "https://api.todoist.com/rest/v2"``.
These tests assert that all egress routes through ``SandboxHttpClient`` (the
fail-closed guard: private-IP block + whitelist + redirect re-check) rather than
raw ``urllib.urlopen``:

- a GET call routes through the guard and returns parsed JSON;
- a POST with a body routes through the guard with ``json_body`` set;
- an empty response body is returned as ``{}``;
- a non-whitelisted host is BLOCKED (no fetch, error dict returned);
- a private/loopback host is BLOCKED (no fetch, error dict returned).

DNS note: private IP *literals* are parsed by ``ipaddress`` without any DNS, so
the SSRF-block tests need no network; public-host tests mock
``_resolves_to_private`` (real public hosts resolve to captive addresses).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "todoist" / "agent.py"
)


def _load_agent():
    """Import the todoist agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("todoist_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    inst = agent_mod.TodoistAgent()
    inst._api_key = "test-token"
    return inst


def _mock_opener_open(body: bytes, url: str = "https://api.todoist.com/rest/v2/tasks"):
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
        "host",
        [
            "169.254.169.254",
            "127.0.0.1",
            "10.0.0.5",
            "192.168.0.1",
        ],
    )
    def test_private_host_blocked(self, agent_mod, host):
        """A private/loopback host injected via BASE_URL is blocked; no fetch."""
        original_base = agent_mod.BASE_URL
        agent_mod.BASE_URL = f"https://{host}/rest/v2"
        inst = agent_mod.TodoistAgent()
        inst._api_key = "test-token"
        try:
            with patch("urllib.request.OpenerDirector.open") as op:
                result = inst._api_call("GET", "/tasks")
        finally:
            agent_mod.BASE_URL = original_base
        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()


class TestApiCallGetRoutesGuard:
    def test_get_tasks_routes_through_guard(self, agent):
        """A normal GET /tasks call routes through the guard and parses JSON."""
        body = json.dumps([{"id": "1", "content": "Buy milk", "priority": 1}]).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ):
            result = agent._api_call("GET", "/tasks")
        assert result == [{"id": "1", "content": "Buy milk", "priority": 1}]

    def test_get_empty_response_returns_empty_dict(self, agent):
        """A GET that returns an empty body returns ``{}`` (not a JSON error)."""
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(b"")
        ):
            result = agent._api_call("GET", "/tasks/999/close")
        assert result == {}


class TestApiCallPostRoutesGuard:
    def test_post_with_json_body_routes_through_guard(self, agent):
        """A POST with json_body routes through the guard and returns parsed JSON."""
        task = {"id": "42", "content": "Write tests", "priority": 2}
        body = json.dumps(task).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(body)
        ):
            result = agent._api_call("POST", "/tasks", {"content": "Write tests", "priority": 2})
        assert result == task

    def test_post_empty_response_returns_empty_dict(self, agent):
        """A POST that returns empty body (e.g. close task) returns ``{}``."""
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", _mock_opener_open(b"")
        ):
            result = agent._api_call("POST", "/tasks/99/close")
        assert result == {}


class TestApiCallOffWhitelistBlocked:
    def test_non_todoist_host_blocked(self, agent_mod):
        """Override BASE_URL to a non-whitelisted public host — blocked."""
        original_base = agent_mod.BASE_URL
        agent_mod.BASE_URL = "https://evil.example.com"
        inst = agent_mod.TodoistAgent()
        inst._api_key = "test-token"
        try:
            with patch(
                "kernel.sandbox.http_client._resolves_to_private", return_value=False
            ), patch("urllib.request.OpenerDirector.open") as op:
                result = inst._api_call("GET", "/exfil")
        finally:
            agent_mod.BASE_URL = original_base
        assert isinstance(result, dict)
        assert "error" in result
        op.assert_not_called()
