"""Telegram bot agent — send messages and notifications via Telegram."""

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent
from kernel.sandbox.http_client import HttpRequest, SandboxHttpClient, SandboxHttpError

logger = logging.getLogger(__name__)


class TelegramAgent(BaseAgent):
    """Agent for sending messages and notifications via Telegram Bot API."""

    def __init__(self) -> None:
        super().__init__()
        self._bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._configured = bool(self._bot_token and self._chat_id)

    def get_name(self) -> str:
        """Return agent name."""
        return "telegram"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (send_message, send_notification, get_status).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        if action == "send_message":
            return self._send_message(args.get("text", ""))
        elif action == "send_notification":
            title = args.get("title", "KALI")
            message = args.get("message", "")
            text = f"*{title}*\n{message}"
            return self._send_message(text, parse_mode="Markdown")
        elif action == "get_status":
            return {
                "configured": self._configured,
                "bot_token_set": bool(self._bot_token),
                "chat_id_set": bool(self._chat_id),
            }
        else:
            raise ValueError(f"Unknown action: {action}")

    def _send_message(self, text: str, parse_mode: str | None = None) -> dict[str, Any]:
        """Send a message via Telegram Bot API.

        Args:
            text: Message text to send.
            parse_mode: Optional parse mode (e.g. 'Markdown').

        Returns:
            Status dict with 'status' and optional 'message_id' or 'message'.
        """
        if not self._configured:
            return {
                "status": "error",
                "message": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
            }

        try:
            json_body: dict[str, Any] = {
                "chat_id": self._chat_id,
                "text": text,
            }
            if parse_mode:
                json_body["parse_mode"] = parse_mode

            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            # Route egress through the SSRF/whitelist guard (private-IP block +
            # redirect re-check). Whitelist is api.telegram.org only.
            client = SandboxHttpClient("telegram", allowed_domains=["api.telegram.org"])
            resp = client.request(
                HttpRequest(url=url, method="POST", json_body=json_body, timeout=10.0)
            )
            result = resp.json()

            if result.get("ok"):
                return {"status": "sent", "message_id": result["result"]["message_id"]}
            else:
                return {"status": "error", "message": result.get("description", "Unknown error")}

        except SandboxHttpError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    TelegramAgent().run()
