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

    def test_send_message_configured_success(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            agent = TelegramAgent()

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true, "result": {"message_id": 42}}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = agent.handle_action("send_message", {"text": "hi"})

        assert result["status"] == "sent"
        assert result["message_id"] == 42

    def test_send_message_api_error(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            agent = TelegramAgent()

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": false, "description": "Bad Token"}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = agent.handle_action("send_message", {"text": "hi"})

        assert result["status"] == "error"
        assert result["message"] == "Bad Token"

    def test_send_notification_formats_markdown(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            agent = TelegramAgent()

        captured: list[str] = []

        def fake_urlopen(req, timeout=10):  # type: ignore[no-untyped-def]
            captured.append(req.data.decode())
            mock = MagicMock()
            mock.read.return_value = b'{"ok": true, "result": {"message_id": 1}}'
            mock.__enter__ = lambda s: s
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            agent.handle_action("send_notification", {"title": "Alert", "message": "done"})

        assert captured
        assert "parse_mode=Markdown" in captured[0]
        assert "Alert" in captured[0]
