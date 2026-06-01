"""Messenger Hub agent — read and send messages via messengers (Telegram MVP)."""

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class MessengerHubAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__()
        self._bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._default_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._configured = bool(self._bot_token)
        # Store offset for long polling to acknowledge messages
        self._update_offset = 0

    def get_name(self) -> str:
        return "messenger-hub"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
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
        try:
            params = {
                "chat_id": chat_id,
                "text": text,
            }
            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            data = urllib.parse.urlencode(params).encode()
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())

            if result.get("ok"):
                return {"status": "sent", "message_id": result["result"]["message_id"]}
            return {"status": "error", "message": result.get("description", "Unknown error")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _read_messages(self, limit: int) -> dict[str, Any]:
        try:
            # Note: For MVP, we use getUpdates without acknowledging (so we can re-read if needed), 
            # or we fetch recent and let the LLM filter.
            url = f"https://api.telegram.org/bot{self._bot_token}/getUpdates?limit={limit}"
            if self._update_offset:
                url += f"&offset={self._update_offset}"
                
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())

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
                        "date": msg.get("date")
                    })
            
            return {"status": "success", "messages": messages}
        except Exception as e:
            return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    MessengerHubAgent().run()
