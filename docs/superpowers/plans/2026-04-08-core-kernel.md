# Core Kernel Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python kernel foundation — event bus, config manager, plugin registry, database, scheduler, FastAPI server with WebSocket — that all other sub-projects (voice, agents, UI) will plug into.

**Architecture:** FastAPI async server with in-process pub/sub event bus, YAML config with hot-reload, SQLite persistence via aiosqlite, and a plugin registry that discovers agent manifests. The kernel exposes a WebSocket endpoint for real-time UI communication.

**Tech Stack:** Python 3.12+, FastAPI, aiosqlite, pydantic, pyyaml, watchfiles, uv, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-04-08-jarvis-2026-design.md`

---

## File Structure (this sub-project)

```
jarvis/
├── kernel/
│   ├── __init__.py              # Package init, version
│   ├── __main__.py              # Entry point for python -m kernel
│   ├── main.py                  # FastAPI app factory, routes, WebSocket
│   ├── event_bus.py             # Async pub/sub with wildcard topics
│   ├── config_manager.py        # YAML config loader with hot-reload
│   ├── plugin_registry.py       # Agent manifest discovery and registration
│   ├── database.py              # SQLite schema, migrations, CRUD
│   ├── scheduler.py             # Cron-like time event emitter
│   └── models.py                # Pydantic models (events, config, manifests)
├── agents/                      # Empty dir with example manifest for testing
│   └── _example/
│       └── manifest.yaml
├── config/
│   └── jarvis.yaml              # Default config file
├── tests/
│   ├── conftest.py              # Shared fixtures
│   ├── kernel/
│   │   ├── test_event_bus.py
│   │   ├── test_config_manager.py
│   │   ├── test_plugin_registry.py
│   │   ├── test_database.py
│   │   ├── test_scheduler.py
│   │   ├── test_models.py
│   │   └── test_main.py         # FastAPI + WebSocket integration tests
├── .env.example
├── .gitignore
├── pyproject.toml
├── Makefile
├── CLAUDE.md
└── README.md
```

---

## Chunk 1: Project Setup + Event Bus

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Makefile`
- Create: `CLAUDE.md`
- Create: `kernel/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "jarvis"
version = "0.1.0"
description = "Personal AI Command Center"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "websockets>=14.0",
    "pydantic>=2.10.0",
    "pyyaml>=6.0.2",
    "aiosqlite>=0.20.0",
    "watchfiles>=1.0.0",
    "python-dotenv>=1.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.28.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
```

- [ ] **Step 2: Create .gitignore**

```
__pycache__/
*.py[cod]
.env
*.db
.venv/
dist/
node_modules/
target/
.mypy_cache/
.pytest_cache/
.ruff_cache/
data/
```

- [ ] **Step 3: Create .env.example**

```bash
# LLM API Keys
ANTHROPIC_API_KEY=your-claude-api-key
# OLLAMA_HOST=http://localhost:11434

# Optional integrations
# GOOGLE_CALENDAR_CLIENT_ID=
# GOOGLE_CALENDAR_CLIENT_SECRET=
# HOME_ASSISTANT_URL=
# HOME_ASSISTANT_TOKEN=
```

- [ ] **Step 4: Create Makefile**

```makefile
.PHONY: dev test lint format install

install:
	uv sync --all-extras

dev:
	uv run uvicorn kernel.main:app --reload --port 8000

test:
	uv run pytest -v

lint:
	uv run ruff check kernel/ tests/
	uv run mypy kernel/

format:
	uv run ruff format kernel/ tests/
	uv run ruff check --fix kernel/ tests/
```

- [ ] **Step 5: Create CLAUDE.md**

```markdown
# Jarvis 2026

Personal AI Command Center — voice-controlled agent orchestrator.

## Tech Stack
- Backend: Python 3.12+ / FastAPI
- Package manager: uv
- Tests: pytest (asyncio_mode=auto)
- Linting: ruff + mypy

## Commands
- `make install` — install dependencies
- `make dev` — run dev server
- `make test` — run tests
- `make lint` — check code quality

## Architecture
- `kernel/` — core Python backend (event bus, config, plugin registry, DB)
- `agents/` — agent implementations with manifest.yaml files
- `config/jarvis.yaml` — main configuration
- See `docs/superpowers/specs/2026-04-08-jarvis-2026-design.md` for full spec

## Conventions
- Type hints on all functions
- Google-style docstrings for public functions
- No print() — use logging
- Specific exceptions, not bare except
- Tests in tests/ mirroring source structure
```

- [ ] **Step 6: Create kernel/__init__.py**

```python
"""Jarvis kernel — core backend for the Personal AI Command Center."""

__version__ = "0.1.0"
```

- [ ] **Step 7: Install dependencies and verify**

Run: `uv sync --all-extras`
Expected: dependencies installed, `.venv` created

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .env.example Makefile CLAUDE.md kernel/__init__.py
git commit -m "feat: project scaffolding with pyproject.toml, Makefile, CLAUDE.md"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `kernel/models.py`
- Create: `tests/kernel/test_models.py`
- Create: `tests/__init__.py`
- Create: `tests/kernel/__init__.py`

- [ ] **Step 1: Write failing tests for models**

Create `tests/__init__.py` and `tests/kernel/__init__.py` as empty files.

Create `tests/kernel/test_models.py`:

```python
"""Tests for kernel Pydantic models."""

import uuid
from datetime import datetime, timezone

from kernel.models import (
    AgentManifest,
    AgentToolDef,
    ConfigSchema,
    Event,
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
        ts = datetime(2026, 4, 8, tzinfo=timezone.utc)
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
        """Topic must follow domain.action pattern."""
        import pytest
        with pytest.raises(ValueError):
            Event(topic="invalid", source="test", payload={})

    def test_event_wildcard_topic_rejected(self) -> None:
        """Wildcard topics are for subscriptions, not events."""
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
        assert manifest.permissions == []
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
        assert config.server.port == 8000
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kernel.models'`

- [ ] **Step 3: Implement models**

Create `kernel/models.py`:

```python
"""Pydantic models for Jarvis kernel — events, config, manifests, WebSocket messages."""

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Event(BaseModel):
    """Event Bus message envelope."""

    topic: str
    source: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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
        valid = {"native", "mcp", "http"}
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

    cloud_provider: str = "anthropic"
    cloud_model: str = "claude-sonnet-4-20250514"
    local_provider: str = "ollama"
    local_model: str = "llama3"
    auto_route: bool = True


class ScheduleConfig(BaseModel):
    """Scheduler configuration."""

    morning_hour: int = 8
    evening_hour: int = 22
    timezone: str = "local"  # "local" uses system tz, or IANA like "Europe/Moscow"


class ConfigSchema(BaseModel):
    """Top-level Jarvis configuration schema."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_models.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/models.py tests/
git commit -m "feat: add Pydantic models for events, config, manifests, WS messages"
```

---

### Task 3: Event Bus

**Files:**
- Create: `kernel/event_bus.py`
- Create: `tests/kernel/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_event_bus.py`:

```python
"""Tests for the async pub/sub Event Bus."""

import asyncio

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_event_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kernel.event_bus'`

- [ ] **Step 3: Implement Event Bus**

Create `kernel/event_bus.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_event_bus.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/event_bus.py tests/kernel/test_event_bus.py
git commit -m "feat: async Event Bus with wildcard topic support"
```

---

## Chunk 2: Config Manager + Database

### Task 4: Config Manager

**Files:**
- Create: `kernel/config_manager.py`
- Create: `config/jarvis.yaml`
- Create: `tests/kernel/test_config_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_config_manager.py`:

```python
"""Tests for YAML config manager with hot-reload."""

import tempfile
from pathlib import Path

import pytest
import yaml

from kernel.config_manager import ConfigManager
from kernel.models import ConfigSchema


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    config_file = tmp_path / "jarvis.yaml"
    config_file.write_text(yaml.dump({
        "server": {"host": "127.0.0.1", "port": 8000},
        "voice": {"wake_word": "jarvis"},
    }))
    return tmp_path


class TestConfigManager:
    def test_load_config(self, config_dir: Path) -> None:
        manager = ConfigManager(config_dir / "jarvis.yaml")
        config = manager.load()
        assert isinstance(config, ConfigSchema)
        assert config.server.port == 8000
        assert config.voice.wake_word == "jarvis"

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        manager = ConfigManager(tmp_path / "nonexistent.yaml")
        config = manager.load()
        assert config.server.port == 8000

    def test_load_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        manager = ConfigManager(empty)
        config = manager.load()
        assert config.server.port == 8000

    def test_load_partial_config_merges_defaults(self, tmp_path: Path) -> None:
        partial = tmp_path / "partial.yaml"
        partial.write_text(yaml.dump({"server": {"port": 9999}}))
        manager = ConfigManager(partial)
        config = manager.load()
        assert config.server.port == 9999
        assert config.server.host == "127.0.0.1"
        assert config.voice.wake_word == "jarvis"

    def test_reload_picks_up_changes(self, config_dir: Path) -> None:
        path = config_dir / "jarvis.yaml"
        manager = ConfigManager(path)
        config = manager.load()
        assert config.server.port == 8000

        path.write_text(yaml.dump({"server": {"port": 3000}}))
        config = manager.reload()
        assert config.server.port == 3000

    def test_config_property_returns_cached(self, config_dir: Path) -> None:
        manager = ConfigManager(config_dir / "jarvis.yaml")
        c1 = manager.config
        c2 = manager.config
        assert c1 is c2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_config_manager.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ConfigManager**

Create `kernel/config_manager.py`:

```python
"""YAML configuration manager with hot-reload support."""

import logging
from pathlib import Path

import yaml

from kernel.models import ConfigSchema

logger = logging.getLogger(__name__)


class ConfigManager:
    """Loads and caches YAML config, supports hot-reload.

    If the config file is missing or empty, returns defaults.
    Partial configs are merged with defaults via Pydantic.
    """

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._config: ConfigSchema | None = None

    def load(self) -> ConfigSchema:
        """Load config from YAML file. Returns defaults if file missing or empty."""
        data: dict = {}
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                logger.exception("Failed to parse config at %s, using defaults", self._path)

        self._config = ConfigSchema(**data)
        return self._config

    def reload(self) -> ConfigSchema:
        """Force reload config from disk."""
        logger.info("Reloading config from %s", self._path)
        return self.load()

    @property
    def config(self) -> ConfigSchema:
        """Return cached config, loading from disk on first access."""
        if self._config is None:
            self.load()
        assert self._config is not None
        return self._config
```

- [ ] **Step 4: Create default config file**

Create `config/jarvis.yaml`:

```yaml
# Jarvis 2026 Configuration
server:
  host: "127.0.0.1"
  port: 8000

voice:
  wake_word: "jarvis"
  mode: "wake_word"  # wake_word | push_to_talk | continuous
  stt_model: "base"
  tts_voice: "default"
  vad_threshold: 0.5

llm:
  cloud_provider: "anthropic"
  cloud_model: "claude-sonnet-4-20250514"
  local_provider: "ollama"
  local_model: "llama3"
  auto_route: true

schedule:
  morning_hour: 8
  evening_hour: 22
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_config_manager.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/config_manager.py config/jarvis.yaml tests/kernel/test_config_manager.py
git commit -m "feat: YAML config manager with hot-reload and defaults"
```

---

### Task 5: Database Layer

**Files:**
- Create: `kernel/database.py`
- Create: `tests/kernel/test_database.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_database.py`:

```python
"""Tests for SQLite database layer."""

from pathlib import Path

import pytest

from kernel.database import Database


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


class TestDatabase:
    async def test_initialize_creates_tables(self, db: Database) -> None:
        tables = await db.list_tables()
        assert "conversations" in tables
        assert "agent_configs" in tables
        assert "dashboard_data" in tables
        assert "user_preferences" in tables

    async def test_save_and_get_conversation(self, db: Database) -> None:
        await db.save_conversation(
            transcript="what is my schedule",
            intent="calendar.get_events",
            agent="calendar",
            response="You have 3 events today",
            latency_ms=450,
        )
        rows = await db.get_conversations(limit=10)
        assert len(rows) == 1
        assert rows[0]["transcript"] == "what is my schedule"
        assert rows[0]["agent"] == "calendar"

    async def test_save_and_get_agent_config(self, db: Database) -> None:
        await db.save_agent_config("calendar", {"api_key": "test"}, enabled=True)
        config = await db.get_agent_config("calendar")
        assert config is not None
        assert config["config_json"]["api_key"] == "test"
        assert config["enabled"] is True

    async def test_update_agent_config(self, db: Database) -> None:
        await db.save_agent_config("calendar", {"v": 1}, enabled=True)
        await db.save_agent_config("calendar", {"v": 2}, enabled=False)
        config = await db.get_agent_config("calendar")
        assert config is not None
        assert config["config_json"]["v"] == 2
        assert config["enabled"] is False

    async def test_get_missing_agent_config_returns_none(self, db: Database) -> None:
        config = await db.get_agent_config("nonexistent")
        assert config is None

    async def test_save_and_get_user_preference(self, db: Database) -> None:
        await db.set_preference("theme", "dark")
        value = await db.get_preference("theme")
        assert value == "dark"

    async def test_get_missing_preference_returns_default(self, db: Database) -> None:
        value = await db.get_preference("missing", default="fallback")
        assert value == "fallback"

    async def test_prune_old_conversations(self, db: Database) -> None:
        await db.save_conversation(transcript="old message")
        # Pruning with 0 days should delete everything
        count = await db.prune_old_conversations(days=0)
        assert count == 1
        rows = await db.get_conversations()
        assert len(rows) == 0

    async def test_save_and_get_dashboard_data(self, db: Database) -> None:
        await db.save_dashboard_data("sleep", {"hours": 7.2, "hrv": 51}, source="garmin")
        data = await db.get_dashboard_data("sleep")
        assert data is not None
        assert data["data_json"]["hours"] == 7.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_database.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Database**

Create `kernel/database.py`:

```python
"""SQLite database layer for Jarvis kernel."""

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    transcript TEXT NOT NULL,
    intent TEXT,
    agent TEXT,
    response TEXT,
    latency_ms INTEGER
);

CREATE TABLE IF NOT EXISTS agent_configs (
    agent_name TEXT PRIMARY KEY,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    installed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dashboard_data (
    widget_name TEXT PRIMARY KEY,
    data_json TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_preferences (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


class Database:
    """Async SQLite database for persisting conversations, configs, and preferences."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open connection and create tables."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("Database initialized at %s", self._path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def is_connected(self) -> bool:
        """Whether the database connection is open."""
        return self._conn is not None

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    async def list_tables(self) -> list[str]:
        """List all table names in the database."""
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def prune_old_conversations(self, days: int = 30) -> int:
        """Delete conversations older than N days. Returns count deleted."""
        cursor = await self._db.execute(
            "DELETE FROM conversations WHERE timestamp < datetime('now', ?)",
            (f"-{days} days",),
        )
        await self._db.commit()
        count = cursor.rowcount
        if count:
            logger.info("Pruned %d conversations older than %d days", count, days)
        return count

    # --- Conversations ---

    async def save_conversation(
        self,
        transcript: str,
        intent: str | None = None,
        agent: str | None = None,
        response: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Save a voice interaction record."""
        await self._db.execute(
            "INSERT INTO conversations (transcript, intent, agent, response, latency_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (transcript, intent, agent, response, latency_ms),
        )
        await self._db.commit()

    async def get_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent conversations ordered by timestamp desc."""
        cursor = await self._db.execute(
            "SELECT * FROM conversations ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Agent Configs ---

    async def save_agent_config(
        self, agent_name: str, config: dict[str, Any], enabled: bool = True
    ) -> None:
        """Upsert agent configuration."""
        await self._db.execute(
            "INSERT INTO agent_configs (agent_name, config_json, enabled, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(agent_name) DO UPDATE SET "
            "config_json=excluded.config_json, enabled=excluded.enabled, "
            "updated_at=CURRENT_TIMESTAMP",
            (agent_name, json.dumps(config), enabled),
        )
        await self._db.commit()

    async def get_agent_config(self, agent_name: str) -> dict[str, Any] | None:
        """Get agent config by name. Returns None if not found."""
        cursor = await self._db.execute(
            "SELECT * FROM agent_configs WHERE agent_name = ?", (agent_name,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["config_json"] = json.loads(result["config_json"])
        return result

    # --- User Preferences ---

    async def set_preference(self, key: str, value: Any) -> None:
        """Set a user preference (upsert)."""
        await self._db.execute(
            "INSERT INTO user_preferences (key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value)),
        )
        await self._db.commit()

    async def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference by key."""
        cursor = await self._db.execute(
            "SELECT value_json FROM user_preferences WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    # --- Dashboard Data ---

    async def save_dashboard_data(
        self, widget_name: str, data: dict[str, Any], source: str | None = None
    ) -> None:
        """Upsert dashboard widget data."""
        await self._db.execute(
            "INSERT INTO dashboard_data (widget_name, data_json, source, timestamp) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(widget_name) DO UPDATE SET "
            "data_json=excluded.data_json, source=excluded.source, "
            "timestamp=CURRENT_TIMESTAMP",
            (widget_name, json.dumps(data), source),
        )
        await self._db.commit()

    async def get_dashboard_data(self, widget_name: str) -> dict[str, Any] | None:
        """Get latest dashboard data for a widget."""
        cursor = await self._db.execute(
            "SELECT * FROM dashboard_data WHERE widget_name = ?", (widget_name,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["data_json"] = json.loads(result["data_json"])
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_database.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/database.py tests/kernel/test_database.py
git commit -m "feat: async SQLite database with conversations, configs, preferences, dashboard"
```

---

## Chunk 3: Plugin Registry + Scheduler

### Task 6: Plugin Registry

**Files:**
- Create: `kernel/plugin_registry.py`
- Create: `agents/_example/manifest.yaml`
- Create: `tests/kernel/test_plugin_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_plugin_registry.py`:

```python
"""Tests for agent plugin registry."""

from pathlib import Path

import pytest
import yaml

from kernel.models import AgentManifest
from kernel.plugin_registry import PluginRegistry


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    # Create two agent directories with manifests
    cal_dir = tmp_path / "calendar"
    cal_dir.mkdir()
    (cal_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "calendar",
        "version": "1.0.0",
        "description": "Calendar agent",
        "capabilities": ["calendar.read", "calendar.write"],
        "tools": [{"name": "get_events", "description": "Get events", "parameters": {}}],
        "protocol": "native",
        "permissions": ["network"],
    }))

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "tasks",
        "version": "1.0.0",
        "description": "Tasks agent",
        "capabilities": ["tasks.read", "tasks.write"],
        "protocol": "native",
    }))

    return tmp_path


@pytest.fixture
def registry(agents_dir: Path) -> PluginRegistry:
    return PluginRegistry(agents_dir)


class TestPluginRegistry:
    def test_discover_agents(self, registry: PluginRegistry) -> None:
        agents = registry.discover()
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"calendar", "tasks"}

    def test_get_agent_by_name(self, registry: PluginRegistry) -> None:
        registry.discover()
        agent = registry.get("calendar")
        assert agent is not None
        assert agent.name == "calendar"

    def test_get_missing_agent_returns_none(self, registry: PluginRegistry) -> None:
        registry.discover()
        assert registry.get("nonexistent") is None

    def test_get_all_tools(self, registry: PluginRegistry) -> None:
        registry.discover()
        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "calendar__get_events"

    def test_find_agent_by_tool_name(self, registry: PluginRegistry) -> None:
        registry.discover()
        agent = registry.find_agent_for_tool("calendar__get_events")
        assert agent is not None
        assert agent.name == "calendar"

    def test_skip_invalid_manifest(self, agents_dir: Path) -> None:
        bad_dir = agents_dir / "broken"
        bad_dir.mkdir()
        (bad_dir / "manifest.yaml").write_text("not: valid: yaml: [")

        registry = PluginRegistry(agents_dir)
        agents = registry.discover()
        assert len(agents) == 2  # broken skipped

    def test_skip_dir_without_manifest(self, agents_dir: Path) -> None:
        (agents_dir / "no_manifest").mkdir()
        registry = PluginRegistry(agents_dir)
        agents = registry.discover()
        assert len(agents) == 2

    def test_list_registered(self, registry: PluginRegistry) -> None:
        registry.discover()
        registered = registry.list_registered()
        assert len(registered) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_plugin_registry.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PluginRegistry**

Create `kernel/plugin_registry.py`:

```python
"""Agent plugin registry — discovers and manages agent manifests."""

import logging
from pathlib import Path
from typing import Any

import yaml

from kernel.models import AgentManifest

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Discovers agent manifests in a directory and provides lookup APIs.

    Each agent lives in its own subdirectory with a manifest.yaml.
    Tools from manifests are namespaced as '{agent_name}__{tool_name}'.
    """

    def __init__(self, agents_dir: Path) -> None:
        self._agents_dir = agents_dir
        self._agents: dict[str, AgentManifest] = {}

    def discover(self) -> list[AgentManifest]:
        """Scan agents directory for manifest.yaml files and register them."""
        self._agents.clear()

        if not self._agents_dir.exists():
            logger.warning("Agents directory not found: %s", self._agents_dir)
            return []

        for agent_dir in sorted(self._agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            manifest_path = agent_dir / "manifest.yaml"
            if not manifest_path.exists():
                continue

            try:
                raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                manifest = AgentManifest(**raw)
                self._agents[manifest.name] = manifest
                logger.info("Registered agent: %s v%s", manifest.name, manifest.version)
            except Exception:
                logger.exception("Failed to load manifest from %s", manifest_path)

        return list(self._agents.values())

    def get(self, name: str) -> AgentManifest | None:
        """Get agent manifest by name."""
        return self._agents.get(name)

    def list_registered(self) -> list[AgentManifest]:
        """List all registered agent manifests."""
        return list(self._agents.values())

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all agent tools formatted for LLM function calling.

        Tool names are namespaced: '{agent_name}__{tool_name}'.
        """
        tools: list[dict[str, Any]] = []
        for agent in self._agents.values():
            for tool in agent.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{agent.name}__{tool.name}",
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": tool.parameters,
                        },
                    },
                })
        return tools

    def find_agent_for_tool(self, tool_name: str) -> AgentManifest | None:
        """Find which agent owns a namespaced tool name."""
        if "__" not in tool_name:
            return None
        agent_name = tool_name.split("__")[0]
        return self._agents.get(agent_name)
```

- [ ] **Step 4: Create example agent manifest**

Create `agents/_example/manifest.yaml`:

```yaml
# Example agent manifest — copy this directory to create a new agent
name: example
version: "0.1.0"
description: "Example agent for reference"
capabilities:
  - example.hello
tools:
  - name: say_hello
    description: "Say hello to someone"
    parameters:
      name: { type: string, description: "Person's name" }
protocol: native
permissions: []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_plugin_registry.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/plugin_registry.py agents/_example/manifest.yaml tests/kernel/test_plugin_registry.py
git commit -m "feat: plugin registry with agent manifest discovery and LLM tool formatting"
```

---

### Task 7: Scheduler

**Files:**
- Create: `kernel/scheduler.py`
- Create: `tests/kernel/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_scheduler.py`:

```python
"""Tests for time-based event scheduler."""

from unittest.mock import AsyncMock

import pytest

from kernel.event_bus import EventBus
from kernel.models import ScheduleConfig
from kernel.scheduler import Scheduler


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def scheduler(bus: EventBus) -> Scheduler:
    config = ScheduleConfig(morning_hour=8, evening_hour=22)
    return Scheduler(bus, config)


class TestScheduler:
    async def test_emit_event(self, scheduler: Scheduler, bus: EventBus) -> None:
        handler = AsyncMock()
        bus.subscribe("schedule.morning", handler)

        await scheduler.emit("schedule.morning")

        handler.assert_called_once()
        event = handler.call_args[0][0]
        assert event.topic == "schedule.morning"
        assert event.source == "scheduler"

    async def test_emit_custom_event(self, scheduler: Scheduler, bus: EventBus) -> None:
        handler = AsyncMock()
        bus.subscribe("schedule.custom", handler)

        await scheduler.emit("schedule.custom")

        handler.assert_called_once()

    def test_get_schedule_info(self, scheduler: Scheduler) -> None:
        info = scheduler.get_schedule_info()
        assert info["morning_hour"] == 8
        assert info["evening_hour"] == 22

    async def test_start_and_stop(self, scheduler: Scheduler) -> None:
        """Scheduler starts and stops without errors."""
        scheduler.start()
        assert scheduler.is_running
        await scheduler.stop()
        assert not scheduler.is_running
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_scheduler.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Scheduler**

Create `kernel/scheduler.py`:

```python
"""Time-based event scheduler for the Jarvis kernel."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from kernel.event_bus import EventBus
from kernel.models import Event, ScheduleConfig

logger = logging.getLogger(__name__)


class Scheduler:
    """Emits time-based events (morning, evening, hourly) on the Event Bus.

    Uses local time for scheduling (configurable timezone).
    """

    def __init__(self, event_bus: EventBus, config: ScheduleConfig) -> None:
        self._bus = event_bus
        self._config = config
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_morning: str = ""
        self._last_evening: str = ""
        self._last_hourly: int = -1
        self._tz = self._resolve_tz(config.timezone)

    @staticmethod
    def _resolve_tz(tz_str: str) -> ZoneInfo | None:
        """Resolve timezone config to ZoneInfo. None means system local time."""
        if tz_str == "local":
            return None  # datetime.now() without tz uses system local
        try:
            return ZoneInfo(tz_str)
        except (KeyError, ValueError):
            logger.warning("Invalid timezone '%s', using system local", tz_str)
            return None

    def _now(self) -> datetime:
        """Get current time in configured timezone."""
        if self._tz:
            return datetime.now(self._tz)
        return datetime.now().astimezone()

    async def emit(self, topic: str) -> None:
        """Manually emit a scheduled event."""
        event = Event(
            topic=topic,
            source="scheduler",
            payload={"triggered_at": datetime.now(timezone.utc).isoformat()},
        )
        await self._bus.publish(event)
        logger.info("Scheduler emitted: %s", topic)

    def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the background scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_schedule_info(self) -> dict[str, Any]:
        """Return current schedule configuration."""
        return {
            "morning_hour": self._config.morning_hour,
            "evening_hour": self._config.evening_hour,
            "is_running": self._running,
        }

    async def _loop(self) -> None:
        """Main scheduler loop — checks local time every 30 seconds."""
        while self._running:
            try:
                now = self._now()
                today = now.strftime("%Y-%m-%d")

                if now.hour == self._config.morning_hour and self._last_morning != today:
                    self._last_morning = today
                    await self.emit("schedule.morning")

                if now.hour == self._config.evening_hour and self._last_evening != today:
                    self._last_evening = today
                    await self.emit("schedule.evening")

                if now.hour != self._last_hourly:
                    self._last_hourly = now.hour
                    await self.emit("schedule.hourly")

            except Exception:
                logger.exception("Scheduler loop error")

            await asyncio.sleep(30)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_scheduler.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/scheduler.py tests/kernel/test_scheduler.py
git commit -m "feat: time-based event scheduler with morning/evening/hourly events"
```

---

## Chunk 4: FastAPI Server + WebSocket + Integration

### Task 8: FastAPI Server with WebSocket

**Files:**
- Create: `kernel/main.py`
- Create: `kernel/__main__.py`
- Create: `tests/kernel/test_main.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing tests**

Create `tests/conftest.py`:

```python
"""Shared test fixtures."""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def sample_agents_dir(tmp_path: Path) -> Path:
    """Create a temp agents directory with a test agent."""
    agent_dir = tmp_path / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "test-agent",
        "version": "1.0.0",
        "description": "Test agent",
        "capabilities": ["test.hello"],
        "tools": [{"name": "greet", "description": "Say hi", "parameters": {}}],
        "protocol": "native",
    }))
    return tmp_path / "agents"


@pytest.fixture
def sample_config_path(tmp_path: Path) -> Path:
    """Create a temp config file."""
    config_path = tmp_path / "jarvis.yaml"
    config_path.write_text(yaml.dump({"server": {"port": 8000}}))
    return config_path
```

Create `tests/kernel/test_main.py`:

```python
"""Integration tests for FastAPI server and WebSocket."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from kernel.main import create_app


@pytest.fixture
async def app(tmp_path, sample_agents_dir, sample_config_path):
    application = create_app(
        config_path=sample_config_path,
        agents_dir=sample_agents_dir,
        db_path=tmp_path / "test.db",
    )
    yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    async def test_health_includes_components(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        data = resp.json()
        assert "components" in data
        assert "event_bus" in data["components"]
        assert "database" in data["components"]


class TestAgentsEndpoint:
    async def test_list_agents(self, client: AsyncClient) -> None:
        resp = await client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-agent"

    async def test_get_agent_tools(self, client: AsyncClient) -> None:
        resp = await client.get("/agents/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "test-agent__greet" in data[0]["function"]["name"]


class TestConfigEndpoint:
    async def test_get_config(self, client: AsyncClient) -> None:
        resp = await client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["server"]["port"] == 8000


class TestWebSocket:
    async def test_websocket_connect_and_receive(self, app) -> None:
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "ui.command", "data": {"command": "ping"}})
                response = ws.receive_json()
                assert response["type"] == "ui.command"
                assert response["data"]["status"] == "received"

    async def test_websocket_unknown_type_returns_error(self, app) -> None:
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "unknown.type", "data": {}})
                response = ws.receive_json()
                assert response["type"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_main.py -v`
Expected: FAIL

- [ ] **Step 3: Implement FastAPI server**

Create `kernel/main.py`:

```python
"""FastAPI application — entry point for the Jarvis kernel."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from kernel import __version__
from kernel.config_manager import ConfigManager
from kernel.database import Database
from kernel.event_bus import EventBus
from kernel.models import Event, WSMessage
from kernel.plugin_registry import PluginRegistry
from kernel.scheduler import Scheduler

logger = logging.getLogger(__name__)


def create_app(
    config_path: Path | None = None,
    agents_dir: Path | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    All state is stored on app.state — no module-level globals.
    """
    load_dotenv()

    resolved_config_path = config_path or Path("config/jarvis.yaml")
    resolved_agents_dir = agents_dir or Path("agents")
    resolved_db_path = db_path or Path("data/jarvis.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        # Initialize all components
        event_bus = EventBus()
        config_manager = ConfigManager(resolved_config_path)
        config_manager.load()
        plugin_registry = PluginRegistry(resolved_agents_dir)
        plugin_registry.discover()
        database = Database(resolved_db_path)
        await database.initialize()
        await database.prune_old_conversations()
        scheduler = Scheduler(event_bus, config_manager.config.schedule)
        scheduler.start()

        # Store on app.state for route access
        app.state.event_bus = event_bus
        app.state.config_manager = config_manager
        app.state.plugin_registry = plugin_registry
        app.state.database = database
        app.state.scheduler = scheduler
        app.state.ws_connections: list[WebSocket] = []

        # Forward events to WebSocket clients
        async def ws_forwarder(event: Event) -> None:
            msg = WSMessage(type=event.topic, data=event.payload)
            raw = msg.model_dump_json()
            disconnected: list[WebSocket] = []
            for ws in app.state.ws_connections:
                try:
                    await ws.send_text(raw)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                app.state.ws_connections.remove(ws)

        event_bus.subscribe("agent.*", ws_forwarder)
        event_bus.subscribe("voice.*", ws_forwarder)
        event_bus.subscribe("ui.*", ws_forwarder)
        event_bus.subscribe("dashboard.*", ws_forwarder)
        event_bus.subscribe("schedule.*", ws_forwarder)
        event_bus.subscribe("system.*", ws_forwarder)

        logger.info("Jarvis kernel started (v%s)", __version__)
        yield

        # Graceful shutdown
        await event_bus.publish(
            Event(topic="system.shutdown", source="kernel", payload={})
        )
        await scheduler.stop()
        await database.close()
        logger.info("Jarvis kernel stopped")

    app = FastAPI(title="Jarvis Kernel", version=__version__, lifespan=lifespan)

    # --- Routes ---

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        s = request.app.state
        return {
            "status": "ok",
            "version": __version__,
            "components": {
                "event_bus": {"subscribers": s.event_bus.subscriber_count},
                "database": {"connected": s.database.is_connected},
                "scheduler": s.scheduler.get_schedule_info(),
            },
        }

    @app.get("/agents")
    async def list_agents(request: Request) -> list[dict[str, Any]]:
        return [a.model_dump() for a in request.app.state.plugin_registry.list_registered()]

    @app.get("/agents/tools")
    async def list_tools(request: Request) -> list[dict[str, Any]]:
        return request.app.state.plugin_registry.get_all_tools()

    @app.get("/config")
    async def get_config(request: Request) -> dict[str, Any]:
        return request.app.state.config_manager.config.model_dump()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        s = ws.app.state
        await ws.accept()
        s.ws_connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(s.ws_connections))

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                    msg = WSMessage(**data)
                    if msg.type == "ui.command":
                        await s.event_bus.publish(
                            Event(
                                topic="ui.command",
                                source="websocket",
                                payload=msg.data,
                            )
                        )
                        await ws.send_json({"type": "ui.command", "data": {"status": "received"}})
                    else:
                        await ws.send_json(
                            {"type": "error", "data": {"message": f"Unknown type: {msg.type}"}}
                        )
                except (json.JSONDecodeError, ValueError) as e:
                    await ws.send_json({"type": "error", "data": {"message": str(e)}})
        except WebSocketDisconnect:
            s.ws_connections.remove(ws)
            logger.info("WebSocket client disconnected (%d remaining)", len(s.ws_connections))

    return app
```

Create `kernel/__main__.py` for `python -m kernel`:

```python
"""Entry point for running kernel directly: python -m kernel"""

import uvicorn

from kernel.main import create_app

app = create_app()
uvicorn.run(app, host="127.0.0.1", port=8000)
```

Update Makefile `dev` target:
```makefile
dev:
	uv run uvicorn kernel.main:create_app --factory --reload --port 8000
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_main.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py kernel/__main__.py tests/kernel/test_main.py tests/conftest.py Makefile
git commit -m "feat: FastAPI server with health, agents, config endpoints and WebSocket"
```

---

### Task 9: Run Full Test Suite + Lint

**Files:**
- No new files

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS (models: 10, event bus: 7, config: 6, database: 9, plugin registry: 8, scheduler: 4, main: 7 = ~51 tests)

- [ ] **Step 2: Run linter**

Run: `uv run ruff check kernel/ tests/`
Expected: No errors. If any, fix them.

- [ ] **Step 3: Fix any lint issues**

Fix any ruff issues found in step 2.

- [ ] **Step 4: Run formatter**

Run: `uv run ruff format kernel/ tests/`
Expected: Files formatted or already clean.

- [ ] **Step 5: Commit any fixes**

```bash
git add kernel/ tests/
git commit -m "chore: lint and format fixes"
```

---

### Task 10: Verify Dev Server Starts

**Files:**
- No new files

- [ ] **Step 1: Start the dev server**

Run: `uv run uvicorn kernel.main:create_app --factory --port 8000 &`
Wait 3 seconds, then test:
Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok","version":"0.1.0",...}`

- [ ] **Step 2: Kill the dev server**

Kill the background uvicorn process.

- [ ] **Step 3: Final commit with README note**

No new commit needed — this is a verification step only.

---

## Summary

After completing all tasks, the kernel provides:

1. **Event Bus** — async pub/sub with wildcard topics
2. **Config Manager** — YAML config with hot-reload and defaults
3. **Database** — async SQLite with conversations, agent configs, preferences, dashboard data
4. **Plugin Registry** — agent manifest discovery with LLM tool formatting
5. **Scheduler** — time-based event emitter (morning, evening, hourly)
6. **FastAPI Server** — REST endpoints (/health, /agents, /config) + WebSocket (/ws)
7. **Pydantic Models** — validated data contracts for all interfaces

**Next sub-project:** Voice Pipeline (STT, TTS, VAD, wake word)
