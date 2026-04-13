"""Reminder skill template — time-based reminders with snooze support."""

import logging
from datetime import datetime, timedelta
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)

_MAX_HISTORY = 100


class ReminderTemplate(SkillTemplate):
    """Send periodic reminders with snooze support.

    Reminders fire based on ``interval_hours`` within the allowed window
    ``start_hour``..``end_hour``. Delivered reminders are recorded in
    ``history.json``; snooze state is kept in ``snooze.json``.

    Config keys:
        message (str): Text of the reminder.
        interval_hours (float): Minimum hours between reminders.
        start_hour (int): Earliest hour (0-23) to fire (default 8).
        end_hour (int): Latest hour (0-23) to fire (default 22).
    """

    @property
    def template_name(self) -> str:
        return "reminder"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch reminder actions.

        Args:
            action: One of "check", "snooze", "history".
            args: Action-specific arguments.
            config: Skill configuration.

        Returns:
            Result dict appropriate for the action.
        """
        if action == "check":
            return await self._check(config)
        if action == "snooze":
            return await self._snooze(args)
        if action == "history":
            return await self._history()
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _check(self, config: dict[str, Any]) -> dict[str, Any]:
        """Check whether the reminder should fire right now.

        Respects start_hour/end_hour window, interval_hours, and active snooze.

        Args:
            config: Skill configuration with message, interval_hours,
                start_hour, end_hour.

        Returns:
            Dict with ``should_fire`` (bool), ``message`` (str if firing),
            and ``reason`` explaining the decision.
        """
        now = datetime.now()
        start_hour: int = int(config.get("start_hour", 8))
        end_hour: int = int(config.get("end_hour", 22))
        interval_hours: float = float(config.get("interval_hours", 1))
        message: str = config.get("message", "Reminder")

        # Check quiet hours
        if not (start_hour <= now.hour < end_hour):
            return {"should_fire": False, "reason": "outside_window"}

        # Check snooze
        snooze: dict[str, Any] = await self.load_data("snooze.json", default={})
        if snooze:
            until_str: str = snooze.get("until", "")
            try:
                until = datetime.fromisoformat(until_str)
                if now < until:
                    return {"should_fire": False, "reason": "snoozed", "snooze_until": until_str}
            except ValueError:
                logger.warning("Invalid snooze timestamp in snooze.json: %s", until_str)

        # Check interval since last delivery
        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        if history:
            last_fired_str: str = history[-1].get("fired_at", "")
            try:
                last_fired = datetime.fromisoformat(last_fired_str)
                if (now - last_fired).total_seconds() < interval_hours * 3600:
                    return {"should_fire": False, "reason": "too_soon"}
            except ValueError:
                logger.warning("Invalid fired_at in history: %s", last_fired_str)

        # Fire the reminder
        entry = {"fired_at": now.isoformat(), "message": message}
        history.append(entry)
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        await self.save_data("history.json", history)
        logger.debug("Reminder '%s' fired at %s", self.skill_name, now.isoformat())
        return {"should_fire": True, "message": message, "fired_at": now.isoformat()}

    async def _snooze(self, args: dict[str, Any]) -> dict[str, Any]:
        """Snooze the reminder for N minutes.

        Args:
            args: Must contain ``minutes`` (int/float).

        Returns:
            Dict with ``snoozed_until`` ISO timestamp.
        """
        minutes: float = float(args.get("minutes", 10))
        until = datetime.now() + timedelta(minutes=minutes)
        await self.save_data("snooze.json", {"until": until.isoformat()})
        logger.debug("Reminder '%s' snoozed until %s", self.skill_name, until.isoformat())
        return {"snoozed_until": until.isoformat(), "minutes": minutes}

    async def _history(self) -> dict[str, Any]:
        """Return all recorded reminder deliveries.

        Returns:
            Dict with ``history`` list of delivery records.
        """
        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        return {"history": history}
