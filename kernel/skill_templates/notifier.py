"""Notifier skill template — send and track notifications.

Honest delivery status (WS-2):
    Local channels (``voice`` / ``notification`` and their Russian aliases
    ``голос`` / ``чат``) are "delivered" by recording them for the voice/UI
    layer to pick up, so they report ``sent``. The ``telegram`` channel is an
    *external* delivery: it reports ``sent`` ONLY when the message actually
    leaves the device via the Telegram Bot API. When Telegram is not
    configured (no bot token / chat id) it reports an honest ``unconfigured``
    status — never a fake ``sent``.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from kernel.agent_keys import agent_is_configured
from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)

_MAX_HISTORY = 100

#: Substrings (lower-cased) that mark a channel as Telegram delivery. Covers the
#: English key and the raw Russian wizard answer ("телеграм").
_TELEGRAM_MARKERS = ("telegram", "телеграм")


def _is_telegram_channel(channel: str) -> bool:
    """Return True if the channel routes to Telegram (English or Russian)."""
    low = channel.lower()
    return any(marker in low for marker in _TELEGRAM_MARKERS)


class NotifierTemplate(SkillTemplate):
    """Record outgoing notifications and track their delivery history.

    Notifications are stored in ``history.json``.

    Config keys:
        notify_channel (str): The channel chosen in the builder wizard
            (e.g. "голос", "телеграм", "чат"). Takes precedence.
        default_channel (str): Legacy fallback channel (default "voice").
    """

    @property
    def template_name(self) -> str:
        return "notifier"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch notifier actions.

        Args:
            action: One of "notify", "history".
            args: Action-specific arguments.
            config: Skill configuration.

        Returns:
            Result dict appropriate for the action.
        """
        if action == "notify":
            return await self._notify(args, config)
        if action == "history":
            return await self._history()
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_channel(self, args: dict[str, Any], config: dict[str, Any]) -> str:
        """Resolve the target channel, honoring the wizard's ``notify_channel``.

        Precedence: explicit ``channel`` arg → ``notify_channel`` config (what
        the builder wizard actually stores) → legacy ``default_channel`` →
        ``"voice"``.
        """
        config_channel = config.get("notify_channel") or config.get("default_channel") or "voice"
        return str(args.get("channel", config_channel))

    async def _notify(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Record a notification and report an honest delivery status.

        Local channels (voice / notification) are recorded and reported as
        ``sent``. The telegram channel is delivered for real when configured
        and reports ``sent`` only on success; otherwise it reports an honest
        non-``sent`` status (``unconfigured`` / ``error``).

        Args:
            args: Must contain ``message`` (str). Optionally ``channel`` (str).
            config: May contain ``notify_channel`` or ``default_channel`` (str).

        Returns:
            Dict with ``status``, ``message``, ``channel``, ``sent_at`` and —
            when delivery did not succeed — a ``reason``.
        """
        message: str = str(args.get("message", ""))
        channel: str = self._resolve_channel(args, config)
        now_str = datetime.now().isoformat()

        if _is_telegram_channel(channel):
            status, extra = await self._notify_telegram(message)
        else:
            status, extra = "sent", {}

        entry: dict[str, Any] = {
            "sent_at": now_str,
            "message": message,
            "channel": channel,
            "status": status,
        }
        await self._append_history(entry)

        logger.debug(
            "Notifier '%s': %s via %s — %r", self.skill_name, status, channel, message,
        )
        return {"status": status, "message": message, "channel": channel, "sent_at": now_str, **extra}

    async def _notify_telegram(self, message: str) -> tuple[str, dict[str, Any]]:
        """Deliver via Telegram when configured; degrade honestly otherwise.

        Returns:
            ``(status, extra)`` where ``status`` is ``"sent"`` only on real
            delivery success, and ``extra`` carries a ``reason`` (and optional
            ``message_id``) for the caller.
        """
        if not agent_is_configured("telegram"):
            return "unconfigured", {
                "reason": "Telegram не настроен (нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).",
            }

        result = await self._deliver_via_telegram(message)
        if result.get("status") == "sent":
            extra: dict[str, Any] = {}
            if "message_id" in result:
                extra["message_id"] = result["message_id"]
            return "sent", extra
        return "error", {"reason": str(result.get("message", "Telegram delivery failed"))}

    async def _deliver_via_telegram(self, message: str) -> dict[str, Any]:
        """Send ``message`` through the real Telegram agent off the event loop.

        Reuses ``agents/telegram`` for token reading and Bot API delivery. The
        agent's send is synchronous (urllib), so it runs in a worker thread to
        avoid blocking the event loop.

        Returns:
            The Telegram agent's result dict (``status`` ``"sent"`` on success).
        """
        from agents.telegram.agent import TelegramAgent

        def _send() -> dict[str, Any]:
            agent = TelegramAgent()
            return agent.handle_action(
                "send_notification", {"title": self.skill_name, "message": message},
            )

        return await asyncio.to_thread(_send)

    async def _append_history(self, entry: dict[str, Any]) -> None:
        """Append a notification record, capping history at ``_MAX_HISTORY``."""
        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        history.append(entry)
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        await self.save_data("history.json", history)

    async def _history(self) -> dict[str, Any]:
        """Return all recorded notifications.

        Returns:
            Dict with ``history`` list of notification records.
        """
        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        return {"history": history}
