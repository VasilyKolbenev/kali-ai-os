"""SQLite database layer for KALI kernel."""

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
            "DELETE FROM conversations WHERE timestamp <= datetime('now', ?)",
            (f"-{days} days",),
        )
        await self._db.commit()
        count = cursor.rowcount
        if count:
            logger.info("Pruned %d conversations older than %d days", count, days)
        return count

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
        result["enabled"] = bool(result["enabled"])
        return result

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
