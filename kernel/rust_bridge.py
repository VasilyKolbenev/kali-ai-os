"""Forward Python event-bus events to the Rust backend's
`POST /_internal/events` endpoint so Rust can fan them out to WebSocket
clients on :3006.

Design notes:
- Fire-and-forget: if Rust is unreachable we log at DEBUG level (not WARN)
  and move on. During early migration a missing Rust must not spam logs.
- Skips events that originated from a WebSocket (`source == "websocket"`)
  to prevent a publish-echo loop — UI commands already re-enter the bus
  directly via Rust's /ws recv-task.
- Per-request timeout is short (default 0.5s). Rust on loopback replies
  immediately; anything longer than that indicates a stall and we drop
  the event rather than slow the publisher.

Rollback: set `window.__KALI_CONFIG__.rustWsUrl = 'ws://127.0.0.1:3005/ws'`
in the Tauri bootstrap (or `VITE_KALI_RUST_WS_URL` for dev). The bridge
keeps POSTing to :3006 (harmless when nothing listens); Python's /ws
carries the traffic exactly as before Phase 2.
"""

import logging
from collections.abc import Awaitable, Callable

import httpx

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)

DEFAULT_RUST_URL = "http://127.0.0.1:3006/_internal/events"

# Topics relayed to Rust. Mirrors the existing ws_forwarder subscriptions
# in kernel/main.py. Anything not in this list stays Python-internal.
RELAYED_TOPIC_GLOBS: tuple[str, ...] = (
    "agent.*",
    "voice.*",
    "ui.*",
    "dashboard.*",
    "canvas.*",
    "schedule.*",
    "system.*",
)


class RustEventBridge:
    """Owns an httpx.AsyncClient pool and forwards events to Rust.

    One instance per kernel; subscribe it to the event bus for each glob in
    `RELAYED_TOPIC_GLOBS` via `subscribe_to_bus()`.
    """

    def __init__(
        self,
        url: str = DEFAULT_RUST_URL,
        timeout_s: float = 0.5,
    ) -> None:
        self._url = url
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def forward(self, event: Event) -> None:
        """Post `event` to Rust. Errors are swallowed with a DEBUG log."""
        # Skip events that originated from the WebSocket — matches Python's
        # ws_forwarder skip and prevents a loop where a client command
        # echoes back as an event which is then re-ingested.
        if event.source == "websocket":
            return
        try:
            await self._client.post(self._url, json=event.model_dump(mode="json"))
        except httpx.HTTPError as err:
            logger.debug(
                "rust_bridge: forward failed (%s): %s",
                type(err).__name__,
                err,
            )

    async def close(self) -> None:
        await self._client.aclose()


def subscribe_to_bus(bridge: RustEventBridge, bus: EventBus) -> None:
    """Subscribe the bridge to each relayed topic glob on the given bus."""
    handler: Callable[[Event], Awaitable[None]] = bridge.forward
    for glob in RELAYED_TOPIC_GLOBS:
        bus.subscribe(glob, handler)
