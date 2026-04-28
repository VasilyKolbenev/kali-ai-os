"""Integration tests for BuilderFlow HTTP endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore


class _MockIntent:
    def __init__(self, type_: str = "skill", template: str = "reminder") -> None:
        self.type = type_
        self.template = template
        self.confidence = 0.9
        self.reason = "mock"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: _MockIntent(),
    )

    # Import inside fixture to allow monkeypatch at module level
    from kernel.main import create_app

    app = create_app()
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    app.state.builder_flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=tmp_path / "agents",
        skill_executor=executor,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_start_returns_session(client):
    r = await client.post("/builder/start", json={"request": "Напомни пить воду каждые 2 часа"})
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"]
    assert data["question"]
    assert data["total_steps"] >= 1


async def test_start_rejects_empty_request(client):
    r = await client.post("/builder/start", json={"request": ""})
    assert r.status_code == 400


async def test_full_happy_path(client):
    r = await client.post("/builder/start", json={"request": "Напомни пить воду"})
    sid = r.json()["session_id"]
    total = r.json()["total_steps"]

    for i in range(total):
        r = await client.post("/builder/answer", json={"session_id": sid, "answer": f"ответ-{i}"})
        data = r.json()
        if data["done"]:
            assert data["preview"]["name"]
            break

    r = await client.post("/builder/deploy", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["status"] == "deployed"


async def test_cancel_mid_flow(client):
    r = await client.post("/builder/start", json={"request": "Напомни"})
    sid = r.json()["session_id"]

    r = await client.post("/builder/cancel", json={"session_id": sid})
    assert r.status_code == 200

    r = await client.post("/builder/answer", json={"session_id": sid, "answer": "x"})
    assert r.status_code == 404


from unittest.mock import AsyncMock, MagicMock


async def test_extract_endpoint_complete_path(client, monkeypatch):
    """Full extraction → 200 with spec field, session_id available for /deploy."""
    monkeypatch.setattr(
        "kernel.builder.extractor._call_llm",
        lambda r: {
            "type": "skill",
            "template": "tracker",
            "name_hint": "treker-vody",
            "extracted": {
                "interval": "2 часа",
                "goal": "2 литра",
                "notify_channel": "чат",
            },
            "confidence": 0.9,
        },
    )
    r = await client.post(
        "/builder/extract",
        json={"request": "трекер воды два литра каждые 2 часа в чат"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["complete"] is True
    assert data["session_id"]
    assert data["spec"]["name"] == "treker-vody"
    assert data["spec"]["config"]["interval"] == "2 часа"


async def test_extract_endpoint_partial_path(client, monkeypatch):
    monkeypatch.setattr(
        "kernel.builder.extractor._call_llm",
        lambda r: {
            "type": "skill",
            "template": "tracker",
            "name_hint": "treker-vody",
            "extracted": {"goal": "2 литра"},
            "confidence": 0.7,
        },
    )
    r = await client.post(
        "/builder/extract",
        json={"request": "трекер 2 литра"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["complete"] is False
    assert data["next_question"] == "Как часто напоминать?"
    assert data["step"] == 1
    assert data["total_steps"] == 3


async def test_extract_endpoint_rejects_empty_request(client):
    r = await client.post("/builder/extract", json={"request": ""})
    assert r.status_code == 400
