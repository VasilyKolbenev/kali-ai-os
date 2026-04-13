"""Time-based event scheduler for the KALI kernel."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from croniter import CroniterBadCronError, croniter

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
        self._cron_jobs: dict[str, dict[str, Any]] = {}

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

    def register_cron(self, name: str, cron_expr: str, topic: str | None = None) -> None:
        """Register a dynamic cron job.

        Args:
            name: Unique identifier for this cron job.
            cron_expr: Standard 5-field cron expression (e.g. "0 */2 * * *").
            topic: Event topic to emit. Defaults to "schedule.cron.{name}".

        Raises:
            ValueError: If cron_expr is not a valid cron expression.
        """
        if not croniter.is_valid(cron_expr):
            raise ValueError(f"Invalid cron expression: '{cron_expr}'")
        resolved_topic = topic or f"schedule.cron.{name}"
        now = datetime.now()
        next_run: datetime = croniter(cron_expr, now).get_next(datetime)
        self._cron_jobs[name] = {
            "cron_expr": cron_expr,
            "topic": resolved_topic,
            "next_run": next_run,
        }
        logger.info("Registered cron job '%s': %s -> %s", name, cron_expr, resolved_topic)

    def unregister_cron(self, name: str) -> bool:
        """Remove a cron job by name.

        Args:
            name: Cron job identifier to remove.

        Returns:
            True if the job existed and was removed, False otherwise.
        """
        removed = self._cron_jobs.pop(name, None) is not None
        if removed:
            logger.info("Unregistered cron job '%s'", name)
        return removed

    def list_cron_jobs(self) -> dict[str, dict[str, Any]]:
        """Return all registered cron jobs with their metadata.

        Returns:
            Dict mapping job name to job info (cron_expr, topic, next_run).
        """
        return dict(self._cron_jobs)

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

                # Dynamic cron jobs
                now_naive = now.replace(tzinfo=None)
                for job_name, job in list(self._cron_jobs.items()):
                    next_run: datetime = job["next_run"]
                    if now_naive >= next_run:
                        await self.emit(job["topic"])
                        job["next_run"] = croniter(job["cron_expr"], now_naive).get_next(datetime)
                        logger.debug(
                            "Cron job '%s' fired; next at %s", job_name, job["next_run"]
                        )

            except Exception:
                logger.exception("Scheduler loop error")

            await asyncio.sleep(30)
