"""SSRF-guard tests for the messenger-hub agent's egress calls.

``agents/messenger-hub/agent.py`` has two call sites:
- ``_send_message``: POST to ``https://api.telegram.org/bot{token}/sendMessage``
- ``_read_messages``: GET  to ``https://api.telegram.org/bot{token}/getUpdates``

Both must route through ``SandboxHttpClient`` (private-IP block + domain
whitelist + redirect re-check). These tests assert:

- sendMessage routes through the guard (json_body, not form-encoded);
- getUpdates routes through the guard (params dict, not query-string URL);
- off-whitelist host is blocked;
- private/loopback host is blocked, raw urllib never called.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "agents" / "messenger-hub" / "agent.py"
)


def _load_agent():
    """Import the messenger-hub agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("messenger_hub_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    inst = agent_mod.MessengerHubAgent()
    inst._bot_token = "test-bot-token"
    inst._configured = True
    return inst


def _mock_opener_open(body: bytes, url: str = "https://api.telegram.org/x"):
    """Mock for ``OpenerDirector.open`` — the guard fetches via its opener."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = url
    mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_resp)


class TestSendMessageRoutesThrough:
    def test_send_message_json_body_routes_through_guard(self, agent_mod, agent):
        """_send_message POSTs json_body via SandboxHttpClient, not raw urllib.

        Verified by patching ``SandboxHttpClient.request`` directly — if the
        agent still uses raw urllib the spy is never called and the test fails.
        """
        from kernel.sandbox.http_client import HttpResponse, SandboxHttpClient

        fake_resp = HttpResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=json.dumps({"ok": True, "result": {"message_id": 42}}).encode(),
            url="https://api.telegram.org/x",
        )
        with patch.object(SandboxHttpClient, "request", return_value=fake_resp) as spy:
            result = agent._send_message("123", "hello")
        spy.assert_called_once()
        req_arg = spy.call_args[0][0]
        assert req_arg.method == "POST"
        assert req_arg.json_body is not None, "Expected json_body, not form-encoded data"
        assert req_arg.json_body.get("chat_id") == "123"
        assert req_arg.json_body.get("text") == "hello"
        assert result == {"status": "sent", "message_id": 42}

    def test_send_message_api_error_returns_error_dict(self, agent):
        """_send_message: Telegram ok=False propagates as error dict."""
        from kernel.sandbox.http_client import HttpResponse, SandboxHttpClient

        fake_resp = HttpResponse(
            status=200,
            headers={},
            body=json.dumps({"ok": False, "description": "Bad Request"}).encode(),
            url="https://api.telegram.org/x",
        )
        with patch.object(SandboxHttpClient, "request", return_value=fake_resp):
            result = agent._send_message("123", "hello")
        assert result == {"status": "error", "message": "Bad Request"}


class TestReadMessagesRoutesThrough:
    def test_read_messages_get_params_routes_through_guard(self, agent):
        """_read_messages GETs getUpdates via SandboxHttpClient with params.

        Verified by patching ``SandboxHttpClient.request`` directly — if the
        agent still uses raw urllib the spy is never called and the test fails.
        """
        from kernel.sandbox.http_client import HttpResponse, SandboxHttpClient

        update = {
            "update_id": 100,
            "message": {
                "text": "hi",
                "from": {"first_name": "Alice"},
                "chat": {"id": 999},
                "date": 1234567890,
            },
        }
        fake_resp = HttpResponse(
            status=200,
            headers={},
            body=json.dumps({"ok": True, "result": [update]}).encode(),
            url="https://api.telegram.org/x",
        )
        with patch.object(SandboxHttpClient, "request", return_value=fake_resp) as spy:
            result = agent._read_messages(10)
        spy.assert_called_once()
        req_arg = spy.call_args[0][0]
        assert req_arg.method == "GET"
        assert "limit" in req_arg.params, "Expected params dict, not query-string URL"
        assert result["status"] == "success"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["text"] == "hi"
        assert result["messages"][0]["sender"] == "Alice"

    def test_read_messages_api_error_returns_error_dict(self, agent):
        """_read_messages: Telegram ok=False propagates as error dict."""
        from kernel.sandbox.http_client import HttpResponse, SandboxHttpClient

        fake_resp = HttpResponse(
            status=200,
            headers={},
            body=json.dumps({"ok": False, "description": "Unauthorized"}).encode(),
            url="https://api.telegram.org/x",
        )
        with patch.object(SandboxHttpClient, "request", return_value=fake_resp):
            result = agent._read_messages(5)
        assert result == {"status": "error", "message": "Unauthorized"}


class TestOffWhitelistBlocked:
    def test_non_telegram_host_blocked(self, agent, monkeypatch):
        """A URL pointing to a non-whitelisted host is blocked by the guard."""
        # Temporarily override bot token to point to an off-whitelist host.
        # We do this by patching the send method to use a crafted URL.
        from kernel.sandbox.http_client import SandboxHttpClient, HttpRequest, SandboxHttpError

        client = SandboxHttpClient(
            "messenger-hub", allowed_domains=["api.telegram.org"]
        )
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            with pytest.raises(SandboxHttpError):
                client.request(
                    HttpRequest(url="https://evil.example.com/exfil", method="GET")
                )
        op.assert_not_called()


class TestPrivateHostBlocked:
    @pytest.mark.parametrize(
        "url",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://10.0.0.5/secret",
            "https://192.168.0.1/",
        ],
    )
    def test_private_host_blocked_no_fetch(self, agent, url):
        """Private/loopback targets are blocked; raw urllib.urlopen never called."""
        from kernel.sandbox.http_client import SandboxHttpClient, HttpRequest, SandboxHttpError

        client = SandboxHttpClient(
            "messenger-hub", allowed_domains=["api.telegram.org"]
        )
        with patch("urllib.request.OpenerDirector.open") as op:
            with pytest.raises(SandboxHttpError):
                client.request(HttpRequest(url=url, method="GET"))
        op.assert_not_called()
