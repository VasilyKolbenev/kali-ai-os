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
        count = await db.prune_old_conversations(days=0)
        assert count == 1
        rows = await db.get_conversations()
        assert len(rows) == 0

    async def test_save_and_get_dashboard_data(self, db: Database) -> None:
        await db.save_dashboard_data("sleep", {"hours": 7.2, "hrv": 51}, source="garmin")
        data = await db.get_dashboard_data("sleep")
        assert data is not None
        assert data["data_json"]["hours"] == 7.2
