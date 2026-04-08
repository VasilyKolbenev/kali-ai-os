"""Tests for conversation memory."""

from pathlib import Path

import pytest

from kernel.database import Database
from kernel.memory import ConversationMemory


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def memory(db: Database) -> ConversationMemory:
    return ConversationMemory(db)


class TestConversationMemory:
    def test_add_turn(self, memory: ConversationMemory) -> None:
        memory.add_turn("user", "hello")
        memory.add_turn("assistant", "hi there")
        context = memory.get_context()
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[1]["content"] == "hi there"

    def test_context_limit(self, memory: ConversationMemory) -> None:
        for i in range(50):
            memory.add_turn("user", f"msg {i}")
            memory.add_turn("assistant", f"reply {i}")
        context = memory.get_context(max_turns=5)
        assert len(context) == 10  # 5 turns = 10 messages

    def test_clear(self, memory: ConversationMemory) -> None:
        memory.add_turn("user", "hello")
        memory.clear()
        assert len(memory.get_context()) == 0

    async def test_save_interaction(self, memory: ConversationMemory, db: Database) -> None:
        await memory.save_interaction(
            transcript="what's the weather",
            intent="weather.get",
            agent="weather",
            response="Sunny, 25°C",
            latency_ms=200,
        )
        rows = await db.get_conversations(limit=1)
        assert len(rows) == 1
        assert rows[0]["transcript"] == "what's the weather"

    def test_auto_prune_old_context(self, memory: ConversationMemory) -> None:
        for i in range(100):
            memory.add_turn("user", f"msg {i}")
        assert len(memory._session_context) <= 40  # MAX_CONTEXT_TURNS * 2
