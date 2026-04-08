"""Tests for the async pub/sub Event Bus."""

import pytest

from kernel.event_bus import EventBus
from kernel.models import Event


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestEventBus:
    async def test_subscribe_and_publish(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("voice.transcribed", handler)
        await bus.publish(Event(topic="voice.transcribed", source="test", payload={"text": "hi"}))

        assert len(received) == 1
        assert received[0].payload["text"] == "hi"

    async def test_wildcard_subscription(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("agent.*", handler)
        await bus.publish(Event(topic="agent.response", source="test", payload={}))
        await bus.publish(Event(topic="agent.status.update", source="test", payload={}))
        await bus.publish(Event(topic="voice.transcribed", source="test", payload={}))

        assert len(received) == 2

    async def test_multiple_subscribers(self, bus: EventBus) -> None:
        count = {"a": 0, "b": 0}

        async def handler_a(event: Event) -> None:
            count["a"] += 1

        async def handler_b(event: Event) -> None:
            count["b"] += 1

        bus.subscribe("ui.update", handler_a)
        bus.subscribe("ui.update", handler_b)
        await bus.publish(Event(topic="ui.update", source="test", payload={}))

        assert count["a"] == 1
        assert count["b"] == 1

    async def test_unsubscribe(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("ui.update", handler)
        await bus.publish(Event(topic="ui.update", source="test", payload={}))
        assert len(received) == 1

        bus.unsubscribe("ui.update", handler)
        await bus.publish(Event(topic="ui.update", source="test", payload={}))
        assert len(received) == 1

    async def test_no_subscribers_no_error(self, bus: EventBus) -> None:
        await bus.publish(Event(topic="nobody.listens", source="test", payload={}))

    async def test_handler_exception_does_not_break_bus(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def bad_handler(event: Event) -> None:
            raise RuntimeError("boom")

        async def good_handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("test.topic", bad_handler)
        bus.subscribe("test.topic", good_handler)
        await bus.publish(Event(topic="test.topic", source="test", payload={}))

        assert len(received) == 1

    async def test_subscriber_count(self, bus: EventBus) -> None:
        async def handler(event: Event) -> None:
            pass

        bus.subscribe("a.b", handler)
        bus.subscribe("c.d", handler)
        assert bus.subscriber_count == 2
