"""Pydantic models for KALI kernel — events, config, manifests, WebSocket messages."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from kernel.model_registry import default_model, migrate

logger = logging.getLogger(__name__)

VALID_PERMISSIONS = frozenset({
    "storage", "notifications", "event_bus", "network", "agents", "system",
})


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


class PermissionGrant(BaseModel):
    """Individual permission with optional parameters."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        """Validate permission name against known set.

        Args:
            v: Permission name to validate.

        Returns:
            Validated permission name.

        Raises:
            ValueError: If name is not in VALID_PERMISSIONS.
        """
        if v not in VALID_PERMISSIONS:
            raise ValueError(f"Permission must be one of {VALID_PERMISSIONS}, got: {v}")
        return v


class PermissionSet(BaseModel):
    """Collection of permissions with approval tracking."""

    grants: list[PermissionGrant] = Field(default_factory=list)
    user_approved: bool = False
    approval_timestamp: datetime | None = None

    def has(self, name: str) -> bool:
        """Check if a named permission is in the grant list.

        Args:
            name: Permission name to look up.

        Returns:
            True if the permission is granted.
        """
        return any(g.name == name for g in self.grants)

    def get_params(self, name: str) -> dict[str, Any]:
        """Get parameters for a named permission.

        Args:
            name: Permission name to look up.

        Returns:
            Params dict, or empty dict if not found.
        """
        for g in self.grants:
            if g.name == name:
                return g.params
        return {}


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
    permissions: PermissionSet = Field(default_factory=PermissionSet)

    @field_validator("permissions", mode="before")
    @classmethod
    def coerce_permissions(cls, v: Any) -> Any:
        """Accept flat list ['storage', 'network'] for backward compat.

        Args:
            v: Raw permissions value — list of strings/dicts, or PermissionSet dict.

        Returns:
            Value suitable for PermissionSet construction.
        """
        if isinstance(v, list):
            grants = []
            for p in v:
                if isinstance(p, str):
                    # Silently skip unknown permissions for backward compat
                    if p in VALID_PERMISSIONS:
                        grants.append(PermissionGrant(name=p))
                elif isinstance(p, dict):
                    grants.append(PermissionGrant(**p))
            return PermissionSet(grants=grants)
        return v

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
    port: int = 3005


class VoiceConfig(BaseModel):
    """Voice pipeline configuration."""

    wake_word: str = "jarvis"
    mode: str = "wake_word"  # wake_word | push_to_talk | off
    stt_model: str = "base"
    tts_voice: str = "default"
    vad_threshold: float = 0.5
    auto_start: bool = False  # If true: pipeline starts with app. Otherwise on-demand.
    # Phase 3 Chunk 8 — engine selector. "python" keeps the legacy
    # in-process pipeline (this module). "rust" disables it; the Rust
    # backend's native /voice/* routes take over. Default stays "python"
    # until Vasily's manual rehearsal validates the Rust path.
    engine: Literal["python", "rust"] = "python"


# Default models per cloud provider (used when user switches provider).
# ``anthropic`` is sourced from the machine-readable registry
# (``config/model_registry.json``) so desktop/mobile/UI stay in sync (OPUS-301).
DEFAULT_CLOUD_MODELS: dict[str, str] = {
    "anthropic": default_model("anthropic") or "claude-sonnet-5",
    "openai": "gpt-4.1",
    "google": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-large-latest",
}


class LLMConfig(BaseModel):
    """LLM routing configuration."""

    cloud_provider: str = "anthropic"  # anthropic | openai | google | deepseek | groq | mistral
    cloud_model: str = Field(default_factory=lambda: DEFAULT_CLOUD_MODELS["anthropic"])
    local_provider: str = "ollama"
    local_model: str = "llama3"
    auto_route: bool = True

    @model_validator(mode="after")
    def _migrate_retired_cloud_model(self) -> "LLMConfig":
        """Deterministically migrate a retired stored ``cloud_model`` to the
        provider default with a structured warning (OPUS-301). No-op for
        unmanaged providers or active ids.
        """
        migrated, warning = migrate(self.cloud_provider, self.cloud_model, log=True)
        if warning is not None:
            object.__setattr__(self, "cloud_model", migrated)
        return self


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
