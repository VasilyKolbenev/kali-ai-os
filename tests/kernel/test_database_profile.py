"""Profile-fact persistence: upsert semantics for profile.* topics."""
from pathlib import Path

import pytest

from kernel.database import Database


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "profile.db")
    await database.initialize()
    yield database
    await database.close()


async def test_upsert_inserts_new_fact(db: Database) -> None:
    await db.upsert_user_fact("profile.city", "Ереван")
    facts = await db.get_user_facts()
    assert len(facts) == 1
    assert facts[0]["topic"] == "profile.city"
    assert facts[0]["fact"] == "Ереван"


async def test_upsert_replaces_same_topic_no_duplicates(db: Database) -> None:
    await db.upsert_user_fact("profile.city", "Москва")
    await db.upsert_user_fact("profile.city", "Ереван")
    facts = await db.get_user_facts()
    cities = [f for f in facts if f["topic"] == "profile.city"]
    assert len(cities) == 1
    assert cities[0]["fact"] == "Ереван"


async def test_upsert_does_not_touch_other_topics(db: Database) -> None:
    await db.save_user_fact("hobby", "рыбалка")
    await db.upsert_user_fact("profile.name", "Вася")
    await db.upsert_user_fact("profile.name", "Василий")
    facts = await db.get_user_facts()
    assert any(f["topic"] == "hobby" and f["fact"] == "рыбалка" for f in facts)
    assert len([f for f in facts if f["topic"] == "profile.name"]) == 1


async def test_delete_by_topic(db: Database) -> None:
    await db.upsert_user_fact("profile.city", "Ереван")
    await db.delete_user_facts_by_topic("profile.city")
    assert await db.get_user_facts() == []


async def test_delete_missing_topic_is_noop(db: Database) -> None:
    await db.delete_user_facts_by_topic("profile.city")  # no raise
    assert await db.get_user_facts() == []
