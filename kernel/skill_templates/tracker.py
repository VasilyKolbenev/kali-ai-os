"""Tracker skill template — tracks numeric values over time with daily goals."""

import logging
from datetime import date, timedelta
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)

_MAX_HISTORY = 100


class TrackerTemplate(SkillTemplate):
    """Track numeric values over time with daily goals and trend analysis.

    Stores daily totals in history.json keyed by ISO date strings.

    Config keys:
        unit (str): Unit label (e.g. "cups", "km").
        daily_goal (float): Target value per day.
    """

    @property
    def template_name(self) -> str:
        return "tracker"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch tracker actions.

        Args:
            action: One of "log", "summary", "trend".
            args: Action-specific arguments.
            config: Skill configuration with ``unit`` and ``daily_goal``.

        Returns:
            Result dict appropriate for the action.
        """
        if action == "log":
            return await self._log(args, config)
        if action == "summary":
            return await self._summary(config)
        if action == "trend":
            return await self._trend(config)
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _log(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Log a value for today, accumulating into the daily total.

        Args:
            args: Must contain ``amount`` (float).
            config: Skill config (used for unit label in response).

        Returns:
            Dict with today's running total after the log.
        """
        amount = float(args.get("amount", 0))
        today = date.today().isoformat()
        history: dict[str, float] = await self.load_data("history.json", default={})
        history[today] = history.get(today, 0.0) + amount

        # Trim to last 100 date entries (oldest first, keep newest 100)
        if len(history) > _MAX_HISTORY:
            sorted_keys = sorted(history.keys())
            for old_key in sorted_keys[: len(history) - _MAX_HISTORY]:
                del history[old_key]

        await self.save_data("history.json", history)
        logger.debug("Tracker '%s': logged %.2f for %s", self.skill_name, amount, today)
        return {"date": today, "total": history[today], "unit": config.get("unit", "")}

    async def _summary(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return today's total, goal, remaining and progress percentage.

        Args:
            config: Must contain ``daily_goal`` (float) and ``unit`` (str).

        Returns:
            Dict with today, total, daily_goal, remaining, progress_pct, unit.
        """
        today = date.today().isoformat()
        history: dict[str, float] = await self.load_data("history.json", default={})
        total = history.get(today, 0.0)
        daily_goal = float(config.get("daily_goal", 0))
        remaining = max(0.0, daily_goal - total)
        progress_pct = (total / daily_goal * 100) if daily_goal > 0 else 0.0
        return {
            "date": today,
            "total": total,
            "daily_goal": daily_goal,
            "remaining": remaining,
            "progress_pct": round(progress_pct, 1),
            "unit": config.get("unit", ""),
        }

    async def _trend(self, config: dict[str, Any]) -> dict[str, Any]:
        """Compare 7-day vs 14-day average to determine trend direction.

        Args:
            config: Skill config (unused but kept for consistent signature).

        Returns:
            Dict with avg_7d, avg_14d, direction (up/down/flat/insufficient_data).
        """
        history: dict[str, float] = await self.load_data("history.json", default={})
        today = date.today()

        def _avg(days: int) -> float | None:
            values = []
            for i in range(days):
                key = (today - timedelta(days=i)).isoformat()
                if key in history:
                    values.append(history[key])
            return sum(values) / len(values) if values else None

        avg_7 = _avg(7)
        avg_14 = _avg(14)

        if avg_7 is None or avg_14 is None:
            direction = "insufficient_data"
        elif avg_7 > avg_14 * 1.05:
            direction = "up"
        elif avg_7 < avg_14 * 0.95:
            direction = "down"
        else:
            direction = "flat"

        return {
            "avg_7d": round(avg_7, 2) if avg_7 is not None else None,
            "avg_14d": round(avg_14, 2) if avg_14 is not None else None,
            "direction": direction,
        }
