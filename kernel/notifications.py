"""Cross-platform notification system."""

import logging
from dataclasses import dataclass
from datetime import datetime

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    """A notification to be sent through various channels."""

    title: str
    message: str
    priority: str = "normal"
    source: str = "system"
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class NotificationManager:
    """Manages notifications — desktop, event bus, queue for external delivery."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._queue: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        """Send a notification through all available channels."""
        self._queue.append(notification)
        await self._bus.publish(
            Event(
                topic="notification.new",
                source=notification.source,
                payload={
                    "title": notification.title,
                    "message": notification.message,
                    "priority": notification.priority,
                    "timestamp": notification.timestamp,
                },
            )
        )
        self._try_desktop(notification)
        logger.info("Notification: [%s] %s", notification.title, notification.message)

    def get_pending(self) -> list[Notification]:
        """Get all pending notifications."""
        return list(self._queue)

    def clear_pending(self) -> None:
        """Clear the notification queue."""
        self._queue.clear()

    def _try_desktop(self, notification: Notification) -> None:
        """Try to show a desktop notification (non-critical if fails)."""
        try:
            from plyer import notification as desktop_notif

            desktop_notif.notify(
                title=notification.title,
                message=notification.message,
                timeout=5,
            )
        except ImportError:
            pass
        except Exception:
            logger.debug("Desktop notification failed")
