"""Tests for Telegram bot agent."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from agents.telegram.agent import TelegramAgent


class TestTelegramAgent:
    def test_get_name(self) -> None:
        agent = TelegramAgent()
        assert agent.get_name() == "telegram"

    def test_get_status_not_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            agent = TelegramAgent()
        result = agent.handle_action("get_status", {})
        assert result["configured"] is False
        assert result["bot_token_set"] is False
        assert result["chat_id_set"] is False

    def test_get_status_configured(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": "123"}):
            agent = TelegramAgent()
        result = agent.handle_action("get_status", {})
        assert result["configured"] is True
        assert result["bot_token_set"] is True
        assert result["chat_id_set"] is True

    def test_send_message_not_configured_returns_error(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            agent = TelegramAgent()
        result = agent.handle_action("send_message", {"text": "hello"})
        assert result["status"] == "error"
        assert "TELEGRAM_BOT_TOKEN" in result["message"]

    def test_send_notification_not_configured_returns_error(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            agent = TelegramAgent()
        result = agent.handle_action("send_notification", {"title": "T", "message": "M"})
        assert result["status"] == "error"

    def test_unknown_action_raises(self) -> None:
        agent = TelegramAgent()
        with pytest.raises(ValueError, match="Unknown action"):
            agent.handle_action("nonexistent", {})

    def _make_opener_mock(self, body: bytes) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.url = "https://api.telegram.org/bottoken123/sendMessage"
        mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return MagicMock(return_value=mock_resp)

    def test_send_message_configured_success(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            agent = TelegramAgent()

        body = b'{"ok": true, "result": {"message_id": 42}}'
        with patch("kernel.sandbox.http_client._resolves_to_private", return_value=False), \
                patch("urllib.request.OpenerDirector.open", self._make_opener_mock(body)):
            result = agent.handle_action("send_message", {"text": "hi"})

        assert result["status"] == "sent"
        assert result["message_id"] == 42

    def test_send_message_api_error(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            agent = TelegramAgent()

        body = b'{"ok": false, "description": "Bad Token"}'
        with patch("kernel.sandbox.http_client._resolves_to_private", return_value=False), \
                patch("urllib.request.OpenerDirector.open", self._make_opener_mock(body)):
            result = agent.handle_action("send_message", {"text": "hi"})

        assert result["status"] == "error"
        assert result["message"] == "Bad Token"

    def test_send_notification_formats_markdown(self) -> None:
        import json as _json

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            agent = TelegramAgent()

        captured: list[bytes] = []

        def fake_opener_open(req, data=None, timeout=10):  # type: ignore[no-untyped-def]
            if data is not None:
                captured.append(data)
            mock = MagicMock()
            mock.status = 200
            mock.url = req.full_url
            mock.headers.items.return_value = [("Content-Type", "application/json")]
            mock.read.return_value = b'{"ok": true, "result": {"message_id": 1}}'
            mock.__enter__ = lambda s: s
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        with patch("kernel.sandbox.http_client._resolves_to_private", return_value=False), \
                patch("urllib.request.OpenerDirector.open", side_effect=fake_opener_open):
            agent.handle_action("send_notification", {"title": "Alert", "message": "done"})

        assert captured
        parsed = _json.loads(captured[0].decode())
        assert parsed.get("parse_mode") == "Markdown"
        assert "Alert" in parsed.get("text", "")
