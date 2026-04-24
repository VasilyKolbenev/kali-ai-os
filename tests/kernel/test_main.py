"""Integration tests for FastAPI server and WebSocket."""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from kernel.main import create_app


async def _start_lifespan(app) -> tuple[asyncio.Task, asyncio.Event]:  # type: ignore[type-arg]
    """Trigger ASGI lifespan startup; return (task, shutdown_event)."""
    started: asyncio.Event = asyncio.Event()
    shutdown_event: asyncio.Event = asyncio.Event()

    async def receive() -> dict:  # type: ignore[type-arg]
        if not started.is_set():
            return {"type": "lifespan.startup"}
        await shutdown_event.wait()
        return {"type": "lifespan.shutdown"}

    async def send(message: dict) -> None:  # type: ignore[type-arg]
        if message["type"] == "lifespan.startup.complete":
            started.set()

    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
    task: asyncio.Task = asyncio.create_task(app(scope, receive, send))
    await started.wait()
    return task, shutdown_event


@pytest.fixture
async def app(tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path):
    application = create_app(
        config_path=sample_config_path,
        agents_dir=sample_agents_dir,
        db_path=tmp_path / "test.db",
    )
    task, shutdown_event = await _start_lifespan(application)
    yield application
    shutdown_event.set()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except (TimeoutError, asyncio.CancelledError):
        pass


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
        assert data["server"]["port"] == 3005


class TestConfigPatchEndpoint:
    async def test_patch_voice_wake_word_only_updates_that_field(
        self, client: AsyncClient
    ) -> None:
        resp = await client.patch("/config", json={"voice": {"wake_word": "kali"}})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["voice"]["wake_word"] == "kali"
        assert data["voice"]["mode"] == "wake_word"
        assert data["llm"]["cloud_provider"]

    async def test_patch_persists_across_get(self, client: AsyncClient) -> None:
        before = (await client.get("/config")).json()
        assert before["voice"]["auto_start"] is False
        await client.patch("/config", json={"voice": {"auto_start": True}})
        after = (await client.get("/config")).json()
        assert after["voice"]["auto_start"] is True

    async def test_patch_rejects_invalid_type(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/config", json={"voice": {"vad_threshold": "not-a-number"}}
        )
        assert resp.status_code == 422

    async def test_patch_rejects_null_top_level_section(
        self, client: AsyncClient
    ) -> None:
        resp = await client.patch("/config", json={"voice": None})
        assert resp.status_code == 422
        assert "sections" in resp.json()

    async def test_patch_rejects_non_object_body(self, client: AsyncClient) -> None:
        resp = await client.patch("/config", json=[1, 2, 3])
        assert resp.status_code == 400

    async def test_patch_emits_config_changed_event(
        self, app, client: AsyncClient
    ) -> None:
        received: list = []

        async def capture(event) -> None:  # type: ignore[type-arg]
            received.append(event)

        app.state.event_bus.subscribe("config.changed", capture)

        resp = await client.patch("/config", json={"voice": {"wake_word": "kali"}})
        assert resp.status_code == 200

        assert len(received) == 1
        assert received[0].payload["sections"] == ["voice"]


class TestNotificationsEndpoint:
    async def test_send_notification(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/notifications/send",
            json={"title": "Test", "message": "Hello", "priority": "high"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"

    async def test_pending_notifications(self, client: AsyncClient) -> None:
        await client.post(
            "/notifications/send",
            json={"title": "A", "message": "B"},
        )
        resp = await client.get("/notifications/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[-1]["title"] == "A"
        assert data[-1]["message"] == "B"

    async def test_send_uses_defaults(self, client: AsyncClient) -> None:
        resp = await client.post("/notifications/send", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"


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
