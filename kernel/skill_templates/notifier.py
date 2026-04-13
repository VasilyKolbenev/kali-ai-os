"""Notifier skill template — send and track notifications."""

import logging
from datetime import datetime
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)

_MAX_HISTORY = 100


class NotifierTemplate(SkillTemplate):
    """Record outgoing notifications and track their delivery history.

    Notifications are stored in ``history.json``.

    Config keys:
        default_channel (str): Fallback channel when none provided (default "voice").
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

    async def _notify(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Record a notification and mark it as sent.

        Args:
            args: Must contain ``message`` (str). Optionally ``channel`` (str).
            config: May contain ``default_channel`` (str).

        Returns:
            Dict with ``status``, ``message``, ``channel``, ``sent_at``.
        """
        message: str = str(args.get("message", ""))
        default_channel: str = config.get("default_channel", "voice")
        channel: str = str(args.get("channel", default_channel))
        now_str = datetime.now().isoformat()

        entry: dict[str, Any] = {
            "sent_at": now_str,
            "message": message,
            "channel": channel,
            "status": "sent",
        }

        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        history.append(entry)
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        await self.save_data("history.json", history)

        logger.debug(
            "Notifier '%s': sent via %s — %r", self.skill_name, channel, message,
        )
        return {"status": "sent", "message": message, "channel": channel, "sent_at": now_str}

    async def _history(self) -> dict[str, Any]:
        """Return all recorded notifications.

        Returns:
            Dict with ``history`` list of notification records.
        """
        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        return {"history": history}
