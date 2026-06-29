"""SSRF-guard tests for the telegram agent's ``_send_message`` egress.

``agents/telegram/agent.py`` ``_send_message`` constructs a full URL using the
bot token and calls ``api.telegram.org``. These tests assert that ``_send_message``
routes egress through ``SandboxHttpClient`` (the fail-closed guard: private-IP
block + whitelist + redirect re-check) rather than raw ``urllib.urlopen``:

- a private/loopback/metadata target is BLOCKED (no fetch, error dict returned,
  raw urllib never used);
- a normal ``api.telegram.org`` sendMessage call routes through the guard, passes
  a ``json_body`` (NOT form-encoded), and returns the parsed result;
- a non-whitelisted host cannot be reached via the guard.

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
    Path(__file__).resolve().parents[2] / "agents" / "telegram" / "agent.py"
)


def _load_agent():
    """Import the telegram agent module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("telegram_agent", _AGENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_mod():
    return _load_agent()


@pytest.fixture
def agent(agent_mod):
    """Configured TelegramAgent with test credentials."""
    inst = agent_mod.TelegramAgent()
    inst._bot_token = "test-token-123"
    inst._chat_id = "99999"
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


class TestSendMessageSsrfBlocked:
    """Private/loopback targets are blocked before any network access."""

    def test_private_ip_host_blocked(self, agent_mod):
        """SandboxHttpClient blocks private-IP targets; raw urllib is never called."""
        # We bypass _send_message's URL construction and call the guard directly
        # by testing that a SandboxHttpClient for telegram rejects a private URL.
        from kernel.sandbox.http_client import (
            DomainBlockedError,
            HttpRequest,
            SandboxHttpClient,
        )

        client = SandboxHttpClient("telegram", allowed_domains=["api.telegram.org"])
        private_urls = [
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/sendMessage",
            "https://10.0.0.5/secret",
            "https://192.168.0.1/",
        ]
        with patch("urllib.request.OpenerDirector.open") as op:
            for url in private_urls:
                with pytest.raises(DomainBlockedError):
                    client.request(HttpRequest(url=url, method="POST", timeout=5.0))
            op.assert_not_called()

    def test_non_telegram_domain_blocked(self, agent_mod):
        """A non-whitelisted host is blocked by the domain whitelist."""
        from kernel.sandbox.http_client import (
            DomainBlockedError,
            HttpRequest,
            SandboxHttpClient,
        )

        client = SandboxHttpClient("telegram", allowed_domains=["api.telegram.org"])
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open") as op:
            with pytest.raises(DomainBlockedError):
                client.request(
                    HttpRequest(
                        url="https://evil.example.com/exfil",
                        method="POST",
                        timeout=5.0,
                    )
                )
            op.assert_not_called()


class TestSendMessageRoutesViaGuard:
    """sendMessage routes egress through SandboxHttpClient with json_body."""

    def test_send_message_success_routes_through_guard(self, agent):
        """A normal sendMessage call routes through the guard and returns parsed result."""
        body = json.dumps({"ok": True, "result": {"message_id": 7}}).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open",
            _mock_opener_open(body),
        ):
            result = agent._send_message("Hello KALI")

        assert result == {"status": "sent", "message_id": 7}

    def test_send_message_passes_json_body(self, agent):
        """Guard receives a json_body (not form-encoded bytes) with all params."""
        body = json.dumps({"ok": True, "result": {"message_id": 8}}).encode()
        captured_requests: list = []

        def fake_opener_open(req, data=None, timeout=10):
            captured_requests.append((req, data))
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.url = req.full_url
            mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
            mock_resp.read.return_value = body
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", side_effect=fake_opener_open
        ):
            agent._send_message("test msg", parse_mode="Markdown")

        assert len(captured_requests) == 1
        _, data = captured_requests[0]
        # data must be JSON bytes (not url-encoded form body)
        assert data is not None
        parsed = json.loads(data.decode())
        assert parsed["chat_id"] == "99999"
        assert parsed["text"] == "test msg"
        assert parsed["parse_mode"] == "Markdown"
        # Must NOT be form-encoded (form-encoded would contain '=' and '&')
        assert b"chat_id=99999" not in data

    def test_send_message_no_parse_mode_omits_key(self, agent):
        """When parse_mode is None, json_body does not include the key."""
        body = json.dumps({"ok": True, "result": {"message_id": 9}}).encode()
        captured_requests: list = []

        def fake_opener_open(req, data=None, timeout=10):
            captured_requests.append((req, data))
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.url = req.full_url
            mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
            mock_resp.read.return_value = body
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open", side_effect=fake_opener_open
        ):
            agent._send_message("no mode")

        assert len(captured_requests) == 1
        _, data = captured_requests[0]
        parsed = json.loads(data.decode())
        assert "parse_mode" not in parsed

    def test_send_message_api_error_returns_error_dict(self, agent):
        """When Telegram API returns ok=false, _send_message returns error dict."""
        body = json.dumps({"ok": False, "description": "Unauthorized"}).encode()
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch(
            "urllib.request.OpenerDirector.open",
            _mock_opener_open(body),
        ):
            result = agent._send_message("fail")

        assert result["status"] == "error"
        assert result["message"] == "Unauthorized"

    def test_send_message_sandbox_http_error_returns_error_dict(self, agent):
        """SandboxHttpError is caught and returned as error dict."""
        from kernel.sandbox.http_client import SandboxHttpError

        with patch(
            "kernel.sandbox.http_client.SandboxHttpClient.request",
            side_effect=SandboxHttpError("connection refused"),
        ):
            result = agent._send_message("boom")

        assert result["status"] == "error"
        assert "connection refused" in result["message"]
