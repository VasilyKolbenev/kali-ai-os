"""Focus timer (Pomodoro) with session tracking."""

import asyncio
import logging
import time
from typing import Any

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)


class FocusTimer:
    """Pomodoro-style focus timer with event bus integration."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._active = False
        self._task: asyncio.Task[None] | None = None
        self._start_time: float = 0
        self._duration_minutes: int = 25
        self._label: str = ""
        self._sessions: list[dict[str, Any]] = []

    @property
    def is_active(self) -> bool:
        """Whether a focus session is currently running."""
        return self._active

    async def start(self, duration_minutes: int = 25, label: str = "") -> dict[str, Any]:
        """Start a focus timer session.

        Args:
            duration_minutes: Session duration in minutes. Defaults to 25.
            label: Optional label describing the focus task.

        Returns:
            Dict with status, duration_minutes, label.
        """
        if self._active:
            return {"status": "error", "message": "Timer already running"}

        self._duration_minutes = duration_minutes
        self._label = label
        self._active = True
        self._start_time = time.time()

        await self._bus.publish(Event(
            topic="focus.started",
            source="focus-timer",
            payload={"duration_minutes": duration_minutes, "label": label},
        ))

        self._task = asyncio.create_task(self._countdown(duration_minutes))
        return {"status": "started", "duration_minutes": duration_minutes, "label": label}

    async def stop(self) -> dict[str, Any]:
        """Stop the current focus session early.

        Returns:
            Dict with status and session details.
        """
        if not self._active:
            return {"status": "not_running"}

        self._active = False
        if self._task:
            self._task.cancel()

        elapsed = int(time.time() - self._start_time)
        session = {
            "duration_planned": self._duration_minutes,
            "duration_actual_s": elapsed,
            "label": self._label,
            "completed": False,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._sessions.append(session)

        await self._bus.publish(Event(
            topic="focus.stopped",
            source="focus-timer",
            payload=session,
        ))

        return {"status": "stopped", **session}

    async def _countdown(self, minutes: int) -> None:
        try:
            await asyncio.sleep(minutes * 60)
            self._active = False
            session = {
                "duration_planned": minutes,
                "duration_actual_s": minutes * 60,
                "label": self._label,
                "completed": True,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._sessions.append(session)

            await self._bus.publish(Event(
                topic="focus.completed",
                source="focus-timer",
                payload=session,
            ))
        except asyncio.CancelledError:
            pass

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics for all focus sessions.

        Returns:
            Dict with total_sessions, completed_sessions, total_focus_minutes, is_active.
        """
        completed = [s for s in self._sessions if s.get("completed")]
        total_minutes = sum(s["duration_planned"] for s in completed)
        return {
            "total_sessions": len(self._sessions),
            "completed_sessions": len(completed),
            "total_focus_minutes": total_minutes,
            "is_active": self._active,
        }

    def get_status(self) -> dict[str, Any]:
        """Get current timer status.

        Returns:
            Dict with active flag and remaining/elapsed seconds if running.
        """
        if not self._active:
            return {"active": False}
        elapsed = int(time.time() - self._start_time)
        remaining = max(0, self._duration_minutes * 60 - elapsed)
        return {
            "active": True,
            "remaining_seconds": remaining,
            "label": self._label,
            "elapsed_seconds": elapsed,
        }
