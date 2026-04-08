"""Async pub/sub Event Bus with wildcard topic support."""

import asyncio
import fnmatch
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from kernel.models import Event

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """In-process async pub/sub event bus.

    Supports exact topic matching and wildcard subscriptions (e.g., 'agent.*').
    Handlers are called concurrently via asyncio.gather.
    A failing handler does not prevent other handlers from executing.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, topic_pattern: str, handler: EventHandler) -> None:
        """Subscribe a handler to a topic or wildcard pattern."""
        self._subscribers[topic_pattern].append(handler)

    def unsubscribe(self, topic_pattern: str, handler: EventHandler) -> None:
        """Remove a handler from a topic pattern."""
        handlers = self._subscribers.get(topic_pattern, [])
        if handler in handlers:
            handlers.remove(handler)
            if not handlers:
                del self._subscribers[topic_pattern]

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers concurrently."""
        matching: list[EventHandler] = []
        for pattern, handlers in list(self._subscribers.items()):
            if fnmatch.fnmatch(event.topic, pattern):
                matching.extend(handlers)

        if not matching:
            return

        results = await asyncio.gather(
            *[handler(event) for handler in matching],
            return_exceptions=True,
        )
        for handler, result in zip(matching, results):
            if isinstance(result, Exception):
                logger.exception(
                    "Event handler %s failed for topic %s: %s",
                    handler.__name__,
                    event.topic,
                    result,
                )

    @property
    def subscriber_count(self) -> int:
        """Total number of subscriptions across all patterns."""
        return sum(len(h) for h in self._subscribers.values())
