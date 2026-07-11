"""HTTP contract for the onboarding questionnaire endpoints."""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from kernel.database import Database
from kernel.main import create_app


@pytest.fixture
async def client(tmp_path: Path):
    app = create_app()
    db = Database(tmp_path / "profile.db")
    await db.initialize()
    app.state.database = db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, db
    await db.close()


async def test_post_saves_only_filled_fields(client) -> None:
    c, db = client
    r = await c.post("/profile", json={"name": "Вася", "city": "Ереван"})
    assert r.status_code == 200
    facts = {f["topic"]: f["fact"] for f in await db.get_user_facts()}
    assert facts == {"profile.name": "Вася", "profile.city": "Ереван"}


async def test_post_gender_maps_to_russian(client) -> None:
    c, db = client
    await c.post("/profile", json={"gender": "female"})
    facts = {f["topic"]: f["fact"] for f in await db.get_user_facts()}
    assert facts["profile.gender"] == "женский"


async def test_post_twice_upserts_no_duplicates(client) -> None:
    c, db = client
    await c.post("/profile", json={"city": "Москва"})
    await c.post("/profile", json={"city": "Ереван"})
    facts = [f for f in await db.get_user_facts() if f["topic"] == "profile.city"]
    assert len(facts) == 1 and facts[0]["fact"] == "Ереван"


async def test_post_empty_string_deletes_field(client) -> None:
    c, db = client
    await c.post("/profile", json={"city": "Ереван"})
    await c.post("/profile", json={"city": ""})
    assert all(f["topic"] != "profile.city" for f in await db.get_user_facts())


async def test_post_rejects_bad_gender_and_age(client) -> None:
    c, _ = client
    assert (await c.post("/profile", json={"gender": "attack"})).status_code == 400
    assert (await c.post("/profile", json={"age_range": "9000"})).status_code == 400


async def test_post_rejects_overlong_field(client) -> None:
    c, _ = client
    r = await c.post("/profile", json={"name": "x" * 201})
    assert r.status_code == 400


async def test_get_round_trip(client) -> None:
    c, _ = client
    await c.post("/profile", json={"name": "Вася", "gender": "male", "age_range": "26-35"})
    r = await c.get("/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Вася"
    assert body["gender"] == "male"
    assert body["age_range"] == "26-35"
    assert body["city"] is None
