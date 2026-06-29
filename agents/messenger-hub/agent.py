"""Messenger Hub agent — read and send messages via messengers (Telegram MVP)."""

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent
from kernel.sandbox.http_client import HttpRequest, SandboxHttpClient, SandboxHttpError

logger = logging.getLogger(__name__)

_ALLOWED_DOMAINS = ["api.telegram.org"]


class MessengerHubAgent(BaseAgent):
    """Agent for sending and receiving Telegram messages via the Bot API."""

    def __init__(self) -> None:
        super().__init__()
        self._bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._default_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._configured = bool(self._bot_token)
        # Store offset for long polling to acknowledge messages
        self._update_offset = 0
        self._http = SandboxHttpClient("messenger-hub", allowed_domains=_ALLOWED_DOMAINS)

    def get_name(self) -> str:
        """Return agent name."""
        return "messenger-hub"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (send_message, read_messages).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        if not self._configured:
            return {"status": "error", "message": "TELEGRAM_BOT_TOKEN not configured."}

        if action == "send_message":
            chat_id = args.get("chat_id") or self._default_chat_id
            if not chat_id:
                return {"status": "error", "message": "No chat_id provided and TELEGRAM_CHAT_ID not set."}
            return self._send_message(chat_id, args.get("text", ""))
        elif action == "read_messages":
            return self._read_messages(args.get("limit", 10))
        else:
            raise ValueError(f"Unknown action: {action}")

    def _send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        """Send a Telegram message via the SSRF-guarded HTTP client.

        Args:
            chat_id: Target Telegram chat ID.
            text: Message text to send.

        Returns:
            Dict with 'status' and 'message_id' on success, or 'error'/'message' on failure.
        """
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            resp = self._http.request(
                HttpRequest(
                    url=url,
                    method="POST",
                    json_body={"chat_id": chat_id, "text": text},
                    timeout=10.0,
                )
            )
            result = resp.json()
            if result.get("ok"):
                return {"status": "sent", "message_id": result["result"]["message_id"]}
            return {"status": "error", "message": result.get("description", "Unknown error")}
        except SandboxHttpError as e:
            return {"status": "error", "message": str(e)}

    def _read_messages(self, limit: int) -> dict[str, Any]:
        """Fetch recent Telegram updates via the SSRF-guarded HTTP client.

        Args:
            limit: Maximum number of updates to retrieve.

        Returns:
            Dict with 'status' and 'messages' list on success, or 'error'/'message' on failure.
        """
        url = f"https://api.telegram.org/bot{self._bot_token}/getUpdates"
        params: dict[str, str] = {"limit": str(limit)}
        if self._update_offset:
            params["offset"] = str(self._update_offset)

        try:
            resp = self._http.request(
                HttpRequest(url=url, method="GET", params=params, timeout=10.0)
            )
            result = resp.json()

            if not result.get("ok"):
                return {"status": "error", "message": result.get("description", "Unknown error")}

            messages = []
            for update in result.get("result", []):
                self._update_offset = update["update_id"] + 1
                if "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    sender = msg.get("from", {}).get("first_name", "Unknown")
                    messages.append({
                        "sender": sender,
                        "chat_id": str(msg.get("chat", {}).get("id", "")),
                        "text": msg["text"],
                        "date": msg.get("date"),
                    })

            return {"status": "success", "messages": messages}
        except SandboxHttpError as e:
            return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    MessengerHubAgent().run()
