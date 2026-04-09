"""E2E test — full kernel + agent integration."""

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
async def app(tmp_path: Path):
    agents_dir = Path("agents")
    config_path = Path("config/kali.yaml")
    application = create_app(
        config_path=config_path,
        agents_dir=agents_dir,
        db_path=tmp_path / "e2e.db",
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


class TestE2EFlow:
    async def test_health_shows_all_agents(self, client: AsyncClient) -> None:
        resp = await client.get("/agents")
        data = resp.json()
        names = {a["name"] for a in data}
        assert "system" in names
        assert "tasks" in names
        assert "calendar" in names

    async def test_agent_tools_available(self, client: AsyncClient) -> None:
        resp = await client.get("/agents/tools")
        tools = resp.json()
        tool_names = [t["function"]["name"] for t in tools]
        assert any("system__get_time" in n for n in tool_names)
        assert any("tasks__add_task" in n for n in tool_names)

    async def test_load_and_use_system_agent(self, client: AsyncClient) -> None:
        resp = await client.post("/agents/system/load")
        assert resp.json()["status"] == "loaded"

        resp = await client.get("/agents/running")
        assert any(a["name"] == "system" for a in resp.json())

        resp = await client.get("/agents/system/status")
        assert resp.json()["status"] == "running"

        resp = await client.post("/agents/system/unload")
        assert resp.json()["status"] == "unloaded"

    async def test_voice_status(self, client: AsyncClient) -> None:
        resp = await client.get("/voice/status")
        data = resp.json()
        assert data["available"] is True
        assert data["state"] == "idle"

    async def test_config_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/config")
        data = resp.json()
        assert data["server"]["port"] == 8000
        assert data["voice"]["wake_word"] == "jarvis"
