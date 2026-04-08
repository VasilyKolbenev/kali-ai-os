"""Tests for briefing service."""

import pytest

from kernel.briefing import BriefingService
from kernel.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def service(bus: EventBus) -> BriefingService:
    return BriefingService(bus)


class TestBriefingService:
    async def test_morning_briefing_with_data(self, service: BriefingService) -> None:
        data = {
            "calendar": {"events": [{"title": "Team call"}]},
            "tasks": {"total": 5, "done": 2},
            "weather": {"temperature_c": 22, "condition": "Sunny"},
        }
        text = await service.generate_morning_briefing(data)
        assert "Team call" in text
        assert "3 tasks pending" in text
        assert "22°C" in text

    async def test_morning_briefing_empty(self, service: BriefingService) -> None:
        text = await service.generate_morning_briefing({})
        assert "Good morning" in text
        assert "No events" in text

    async def test_morning_briefing_emits_event(
        self, service: BriefingService, bus: EventBus
    ) -> None:
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("briefing.morning", handler)
        await service.generate_morning_briefing({})
        assert len(received) == 1

    async def test_weekly_review(self, service: BriefingService) -> None:
        data = {
            "tasks": {"done": 28, "total": 35},
            "spending": {"total": 420, "budget": 500},
            "sleep": {"avg_hours": 7.1},
            "focus": {"sessions": 12, "total_minutes": 300},
        }
        text = await service.generate_weekly_review(data)
        assert "28/35" in text
        assert "$420" in text
        assert "7.1h" in text

    async def test_weekly_review_emits_event(self, service: BriefingService, bus: EventBus) -> None:
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("briefing.weekly", handler)
        await service.generate_weekly_review({})
        assert len(received) == 1
