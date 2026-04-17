"""Tests for kernel Pydantic models."""

import uuid
from datetime import UTC, datetime

from kernel.models import (
    AgentManifest,
    AgentToolDef,
    ConfigSchema,
    Event,
    PermissionSet,
    WSMessage,
)


class TestEvent:
    def test_create_event_with_defaults(self) -> None:
        event = Event(topic="voice.transcribed", source="test", payload={"text": "hello"})
        assert event.topic == "voice.transcribed"
        assert event.source == "test"
        assert event.payload == {"text": "hello"}
        assert isinstance(event.timestamp, datetime)
        assert isinstance(uuid.UUID(event.correlation_id), uuid.UUID)

    def test_create_event_with_explicit_fields(self) -> None:
        ts = datetime(2026, 4, 8, tzinfo=UTC)
        event = Event(
            topic="agent.response",
            source="calendar",
            payload={"events": []},
            timestamp=ts,
            correlation_id="custom-id",
        )
        assert event.timestamp == ts
        assert event.correlation_id == "custom-id"

    def test_event_topic_must_contain_dot(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            Event(topic="invalid", source="test", payload={})

    def test_event_wildcard_topic_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            Event(topic="agent.*", source="test", payload={})


class TestWSMessage:
    def test_voice_state_message(self) -> None:
        msg = WSMessage(type="voice.state", data={"state": "listening"})
        assert msg.type == "voice.state"
        raw = msg.model_dump()
        assert raw["type"] == "voice.state"
        assert raw["data"]["state"] == "listening"

    def test_error_message(self) -> None:
        msg = WSMessage(type="error", data={"source": "stt", "message": "mic not found"})
        assert msg.type == "error"


class TestAgentManifest:
    def test_parse_valid_manifest(self) -> None:
        manifest = AgentManifest(
            name="calendar",
            version="1.0.0",
            description="Calendar agent",
            capabilities=["calendar.read", "calendar.write"],
            tools=[
                AgentToolDef(
                    name="get_events",
                    description="Get events",
                    parameters={"date": {"type": "string", "description": "Date"}},
                )
            ],
            protocol="native",
            permissions=["network"],
        )
        assert manifest.name == "calendar"
        assert len(manifest.tools) == 1
        assert manifest.protocol == "native"

    def test_manifest_defaults(self) -> None:
        manifest = AgentManifest(
            name="test",
            version="0.1.0",
            description="Test agent",
        )
        assert manifest.capabilities == []
        assert manifest.tools == []
        assert manifest.protocol == "native"
        assert isinstance(manifest.permissions, PermissionSet)
        assert manifest.permissions.grants == []
        assert manifest.scheduled_events == []

    def test_manifest_invalid_protocol(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            AgentManifest(
                name="test",
                version="0.1.0",
                description="Test",
                protocol="invalid",
            )


class TestConfigSchema:
    def test_default_config(self) -> None:
        config = ConfigSchema()
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 3005
        assert config.voice.wake_word == "jarvis"
        assert config.llm.cloud_provider == "anthropic"
        assert config.llm.local_provider == "ollama"

    def test_custom_config(self) -> None:
        config = ConfigSchema(
            server={"host": "0.0.0.0", "port": 9000},
            voice={"wake_word": "friday"},
        )
        assert config.server.port == 9000
        assert config.voice.wake_word == "friday"
