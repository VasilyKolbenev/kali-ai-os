"""Time-based event scheduler for the KALI kernel."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from kernel.event_bus import EventBus
from kernel.models import Event, ScheduleConfig

logger = logging.getLogger(__name__)


class Scheduler:
    """Emits time-based events (morning, evening, hourly) on the Event Bus.

    Uses local time for scheduling (configurable timezone).
    """

    def __init__(self, event_bus: EventBus, config: ScheduleConfig) -> None:
        self._bus = event_bus
        self._config = config
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_morning: str = ""
        self._last_evening: str = ""
        self._last_hourly: int = -1
        self._tz = self._resolve_tz(config.timezone)

    @staticmethod
    def _resolve_tz(tz_str: str) -> ZoneInfo | None:
        """Resolve timezone config to ZoneInfo. None means system local time."""
        if tz_str == "local":
            return None
        try:
            return ZoneInfo(tz_str)
        except (KeyError, ValueError):
            logger.warning("Invalid timezone '%s', using system local", tz_str)
            return None

    def _now(self) -> datetime:
        """Get current time in configured timezone."""
        if self._tz:
            return datetime.now(self._tz)
        return datetime.now().astimezone()

    async def emit(self, topic: str) -> None:
        """Manually emit a scheduled event."""
        event = Event(
            topic=topic,
            source="scheduler",
            payload={"triggered_at": datetime.now(UTC).isoformat()},
        )
        await self._bus.publish(event)
        logger.info("Scheduler emitted: %s", topic)

    def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the background scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_schedule_info(self) -> dict[str, Any]:
        """Return current schedule configuration."""
        return {
            "morning_hour": self._config.morning_hour,
            "evening_hour": self._config.evening_hour,
            "is_running": self._running,
        }

    async def _loop(self) -> None:
        """Main scheduler loop — checks local time every 30 seconds."""
        while self._running:
            try:
                now = self._now()
                today = now.strftime("%Y-%m-%d")

                if now.hour == self._config.morning_hour and self._last_morning != today:
                    self._last_morning = today
                    await self.emit("schedule.morning")

                if now.hour == self._config.evening_hour and self._last_evening != today:
                    self._last_evening = today
                    await self.emit("schedule.evening")

                if now.hour != self._last_hourly:
                    self._last_hourly = now.hour
                    await self.emit("schedule.hourly")

            except Exception:
                logger.exception("Scheduler loop error")

            await asyncio.sleep(30)
