"""Tests for time-based event scheduler."""

from unittest.mock import AsyncMock

import pytest

from kernel.event_bus import EventBus
from kernel.models import ScheduleConfig
from kernel.scheduler import Scheduler


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def scheduler(bus: EventBus) -> Scheduler:
    config = ScheduleConfig(morning_hour=8, evening_hour=22)
    return Scheduler(bus, config)


class TestScheduler:
    async def test_emit_event(self, scheduler: Scheduler, bus: EventBus) -> None:
        handler = AsyncMock()
        bus.subscribe("schedule.morning", handler)

        await scheduler.emit("schedule.morning")

        handler.assert_called_once()
        event = handler.call_args[0][0]
        assert event.topic == "schedule.morning"
        assert event.source == "scheduler"

    async def test_emit_custom_event(self, scheduler: Scheduler, bus: EventBus) -> None:
        handler = AsyncMock()
        bus.subscribe("schedule.custom", handler)

        await scheduler.emit("schedule.custom")

        handler.assert_called_once()

    def test_get_schedule_info(self, scheduler: Scheduler) -> None:
        info = scheduler.get_schedule_info()
        assert info["morning_hour"] == 8
        assert info["evening_hour"] == 22

    async def test_start_and_stop(self, scheduler: Scheduler) -> None:
        scheduler.start()
        assert scheduler.is_running
        await scheduler.stop()
        assert not scheduler.is_running
