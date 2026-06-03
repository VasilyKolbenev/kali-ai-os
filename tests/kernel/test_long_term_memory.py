"""Tests for long-term (per-user fact) memory — extract → save → recall."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from kernel.database import Database
from kernel.llm_router import LLMResponse
from kernel.long_term_memory import LongTermMemory
from kernel.models import LLMConfig


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "ltm.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def ltm(db: Database) -> LongTermMemory:
    return LongTermMemory(db, LLMConfig())


class TestLongTermMemory:
    async def test_context_string_empty_when_no_facts(self, ltm: LongTermMemory) -> None:
        assert await ltm.get_user_context_string() == ""

    async def test_save_then_recall_formats_facts(
        self, ltm: LongTermMemory, db: Database
    ) -> None:
        await db.save_user_fact("name", "Vasily")
        await db.save_user_fact("job", "builder")
        ctx = await ltm.get_user_context_string()
        assert "<UserFacts>" in ctx and "</UserFacts>" in ctx
        assert "name: Vasily" in ctx
        assert "job: builder" in ctx

    async def test_extract_persists_facts_from_llm(
        self, ltm: LongTermMemory, db: Database
    ) -> None:
        fake = LLMResponse(
            text='[{"topic": "name", "fact": "Vasily"}]',
            tool_calls=None,
            provider_used="local",
            latency_ms=1,
        )
        with patch.object(ltm._llm, "route", new=AsyncMock(return_value=fake)):
            await ltm._extract_facts_bg("Меня зовут Василий")
        facts = await db.get_user_facts()
        assert any(f["topic"] == "name" and f["fact"] == "Vasily" for f in facts)

    async def test_extract_strips_markdown_fence(
        self, ltm: LongTermMemory, db: Database
    ) -> None:
        fake = LLMResponse(
            text='```json\n[{"topic": "city", "fact": "Moscow"}]\n```',
            tool_calls=None,
            provider_used="local",
            latency_ms=1,
        )
        with patch.object(ltm._llm, "route", new=AsyncMock(return_value=fake)):
            await ltm._extract_facts_bg("Я живу в Москве")
        facts = await db.get_user_facts()
        assert any(f["fact"] == "Moscow" for f in facts)

    async def test_extract_ignores_empty_array(
        self, ltm: LongTermMemory, db: Database
    ) -> None:
        fake = LLMResponse(
            text="[]", tool_calls=None, provider_used="local", latency_ms=1
        )
        with patch.object(ltm._llm, "route", new=AsyncMock(return_value=fake)):
            await ltm._extract_facts_bg("просто привет")
        assert await db.get_user_facts() == []
