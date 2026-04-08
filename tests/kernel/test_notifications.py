"""Tests for notification system."""

import pytest

from kernel.event_bus import EventBus
from kernel.notifications import Notification, NotificationManager


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def manager(bus: EventBus) -> NotificationManager:
    return NotificationManager(bus)


class TestNotification:
    def test_create_notification(self) -> None:
        n = Notification(title="Test", message="Hello")
        assert n.title == "Test"
        assert n.priority == "normal"
        assert n.timestamp != ""

    def test_custom_priority(self) -> None:
        n = Notification(title="Alert", message="Urgent!", priority="high")
        assert n.priority == "high"


class TestNotificationManager:
    async def test_send_publishes_event(self, manager: NotificationManager, bus: EventBus) -> None:
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("notification.new", handler)
        await manager.send(Notification(title="Test", message="Hello"))
        assert len(received) == 1
        assert received[0].payload["title"] == "Test"

    async def test_queue_management(self, manager: NotificationManager) -> None:
        await manager.send(Notification(title="A", message="1"))
        await manager.send(Notification(title="B", message="2"))
        assert len(manager.get_pending()) == 2
        manager.clear_pending()
        assert len(manager.get_pending()) == 0
