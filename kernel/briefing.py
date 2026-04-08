"""Morning briefing and weekly review — aggregates data from all agents."""

import logging
from datetime import datetime
from typing import Any

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)


class BriefingService:
    """Generates morning briefings and weekly reviews from agent data."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus

    async def generate_morning_briefing(self, agent_data: dict[str, Any]) -> str:
        """Generate a morning briefing from collected agent data.

        Args:
            agent_data: Dict with keys calendar, tasks, weather, budget, etc.

        Returns:
            Human-readable morning briefing string.
        """
        now = datetime.now()
        parts = [f"Good morning! Today is {now.strftime('%A, %B %d')}."]

        # Calendar
        calendar = agent_data.get("calendar", {})
        events = calendar.get("events", [])
        if events:
            parts.append(f"You have {len(events)} event{'s' if len(events) != 1 else ''} today.")
            first = events[0]
            parts.append(f"First up: {first.get('title', 'Event')}.")
        else:
            parts.append("No events scheduled.")

        # Tasks
        tasks = agent_data.get("tasks", {})
        total = tasks.get("total", 0)
        done = tasks.get("done", 0)
        pending = total - done
        if pending > 0:
            parts.append(f"{pending} task{'s' if pending != 1 else ''} pending.")

        # Weather
        weather = agent_data.get("weather", {})
        if weather.get("temperature_c") is not None:
            temp = weather["temperature_c"]
            condition = weather.get("condition", "")
            parts.append(f"Weather: {temp}°C, {condition}.")

        # Budget
        budget = agent_data.get("budget", {})
        if budget.get("remaining") is not None:
            cat = budget.get("category", "total")
            remaining = budget["remaining"]
            parts.append(f"Budget remaining ({cat}): ${remaining}.")

        briefing = " ".join(parts)

        await self._bus.publish(Event(
            topic="briefing.morning",
            source="briefing-service",
            payload={"text": briefing, "data": agent_data},
        ))

        return briefing

    async def generate_weekly_review(self, agent_data: dict[str, Any]) -> str:
        """Generate a weekly review summary.

        Args:
            agent_data: Dict with keys tasks, spending, sleep, focus, etc.

        Returns:
            Human-readable weekly review string.
        """
        parts = ["Weekly Review:"]

        tasks = agent_data.get("tasks", {})
        if tasks:
            parts.append(f"Tasks: {tasks.get('done', 0)}/{tasks.get('total', 0)} completed.")

        spending = agent_data.get("spending", {})
        if spending:
            total = spending.get("total", 0)
            budget = spending.get("budget", 0)
            if budget:
                pct = round(total / budget * 100) if budget else 0
                parts.append(f"Spending: ${total} of ${budget} budget ({pct}%).")
            else:
                parts.append(f"Total spending: ${total}.")

        sleep = agent_data.get("sleep", {})
        if sleep.get("avg_hours"):
            parts.append(f"Average sleep: {sleep['avg_hours']}h.")

        focus = agent_data.get("focus", {})
        if focus.get("sessions"):
            total_min = focus.get("total_minutes", 0)
            parts.append(f"Focus sessions: {focus['sessions']} ({total_min} min).")

        review = " ".join(parts)

        await self._bus.publish(Event(
            topic="briefing.weekly",
            source="briefing-service",
            payload={"text": review, "data": agent_data},
        ))

        return review
