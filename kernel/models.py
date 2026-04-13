"""Pydantic models for KALI kernel — events, config, manifests, WebSocket messages."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Event(BaseModel):
    """Event Bus message envelope."""

    topic: str
    source: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("topic")
    @classmethod
    def topic_must_be_dotted(cls, v: str) -> str:
        if "." not in v:
            raise ValueError(f"Topic must follow 'domain.action' pattern, got: {v}")
        if "*" in v:
            raise ValueError(f"Wildcard topics are for subscriptions only, got: {v}")
        return v


class WSMessage(BaseModel):
    """WebSocket message between kernel and UI."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentToolDef(BaseModel):
    """Tool definition exposed to LLM for function calling."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentManifest(BaseModel):
    """Agent plugin manifest parsed from manifest.yaml."""

    name: str
    version: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    tools: list[AgentToolDef] = Field(default_factory=list)
    scheduled_events: list[str] = Field(default_factory=list)
    health_check: str = "/health"
    protocol: str = "native"
    permissions: list[str] = Field(default_factory=list)

    @field_validator("protocol")
    @classmethod
    def protocol_must_be_valid(cls, v: str) -> str:
        valid = {"native", "mcp", "http", "skill"}
        if v not in valid:
            raise ValueError(f"Protocol must be one of {valid}, got: {v}")
        return v


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = "127.0.0.1"
    port: int = 8000


class VoiceConfig(BaseModel):
    """Voice pipeline configuration."""

    wake_word: str = "jarvis"
    mode: str = "wake_word"
    stt_model: str = "base"
    tts_voice: str = "default"
    vad_threshold: float = 0.5


class LLMConfig(BaseModel):
    """LLM routing configuration."""

    cloud_provider: str = "anthropic"  # "anthropic" or "openai"
    cloud_model: str = "claude-sonnet-4-20250514"  # or "gpt-5.4", "gpt-5.4-mini"
    local_provider: str = "ollama"
    local_model: str = "llama3"
    auto_route: bool = True


class ScheduleConfig(BaseModel):
    """Scheduler configuration."""

    morning_hour: int = 8
    evening_hour: int = 22
    timezone: str = "local"


class ConfigSchema(BaseModel):
    """Top-level KALI configuration schema."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
