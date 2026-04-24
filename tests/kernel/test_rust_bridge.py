"""Tests for `kernel.rust_bridge.RustEventBridge`."""

from unittest.mock import AsyncMock

import httpx
import pytest

from kernel.event_bus import EventBus
from kernel.models import Event
from kernel.rust_bridge import RELAYED_TOPIC_GLOBS, RustEventBridge, subscribe_to_bus


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> RustEventBridge:
    """Bridge pointed at a black-hole port with its HTTP call mocked."""
    b = RustEventBridge(url="http://127.0.0.1:1")
    mock_post = AsyncMock()
    monkeypatch.setattr(b._client, "post", mock_post)
    b._mock_post = mock_post  # type: ignore[attr-defined]
    return b


class TestRustEventBridge:
    async def test_forward_posts_event_payload(self, bridge: RustEventBridge) -> None:
        event = Event(
            topic="voice.state",
            source="kernel",
            payload={"state": "listening"},
        )
        await bridge.forward(event)
        bridge._mock_post.assert_awaited_once()  # type: ignore[attr-defined]
        _, kwargs = bridge._mock_post.call_args  # type: ignore[attr-defined]
        body = kwargs["json"]
        assert body["topic"] == "voice.state"
        assert body["payload"] == {"state": "listening"}
        assert "timestamp" in body and "correlation_id" in body

    async def test_forward_skips_websocket_sourced_events(
        self, bridge: RustEventBridge
    ) -> None:
        event = Event(topic="ui.command", source="websocket", payload={"name": "x"})
        await bridge.forward(event)
        bridge._mock_post.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_forward_swallows_connection_errors(
        self, bridge: RustEventBridge
    ) -> None:
        bridge._mock_post.side_effect = httpx.ConnectError("refused")  # type: ignore[attr-defined]
        event = Event(topic="voice.state", source="kernel", payload={})
        # Must NOT raise.
        await bridge.forward(event)

    async def test_forward_swallows_timeouts(self, bridge: RustEventBridge) -> None:
        bridge._mock_post.side_effect = httpx.ReadTimeout("slow rust")  # type: ignore[attr-defined]
        event = Event(topic="voice.state", source="kernel", payload={})
        await bridge.forward(event)


class TestSubscribeToBus:
    async def test_subscribes_all_relayed_globs(self) -> None:
        bus = EventBus()
        b = RustEventBridge(url="http://127.0.0.1:1")
        subscribe_to_bus(b, bus)
        assert bus.subscriber_count == len(RELAYED_TOPIC_GLOBS)

    async def test_bridge_receives_events_matching_glob(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = EventBus()
        b = RustEventBridge(url="http://127.0.0.1:1")
        mock_post = AsyncMock()
        monkeypatch.setattr(b._client, "post", mock_post)
        subscribe_to_bus(b, bus)

        await bus.publish(Event(topic="voice.state", source="kernel", payload={}))
        await bus.publish(Event(topic="agent.started", source="kernel", payload={}))
        await bus.publish(Event(topic="irrelevant.topic", source="kernel", payload={}))

        # voice.* and agent.* match → 2 forwards; irrelevant.topic does not.
        assert mock_post.await_count == 2
