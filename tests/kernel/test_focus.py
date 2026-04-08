"""Tests for focus timer."""

import pytest

from kernel.event_bus import EventBus
from kernel.focus import FocusTimer


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def timer(bus: EventBus) -> FocusTimer:
    return FocusTimer(bus)


class TestFocusTimer:
    async def test_start(self, timer: FocusTimer) -> None:
        result = await timer.start(25, "coding")
        assert result["status"] == "started"
        assert timer.is_active
        await timer.stop()

    async def test_stop(self, timer: FocusTimer) -> None:
        await timer.start(25)
        result = await timer.stop()
        assert result["status"] == "stopped"
        assert not timer.is_active

    async def test_double_start(self, timer: FocusTimer) -> None:
        await timer.start(25)
        result = await timer.start(25)
        assert result["status"] == "error"
        await timer.stop()

    async def test_start_emits_event(self, timer: FocusTimer, bus: EventBus) -> None:
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe("focus.started", handler)
        await timer.start(25, "test")
        assert len(received) == 1
        await timer.stop()

    def test_get_stats_empty(self, timer: FocusTimer) -> None:
        stats = timer.get_stats()
        assert stats["total_sessions"] == 0

    def test_get_status_inactive(self, timer: FocusTimer) -> None:
        status = timer.get_status()
        assert status["active"] is False
