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

    Args:
        config_path: Path to jarvis.yaml config file. Defaults to config/jarvis.yaml.
        agents_dir: Path to agents directory. Defaults to agents/.
        db_path: Path to SQLite database file. Defaults to data/jarvis.db.

    Returns:
        Configured FastAPI application instance.
    """
    load_dotenv()

    resolved_config_path = config_path or Path("config/jarvis.yaml")
    resolved_agents_dir = agents_dir or Path("agents")
    resolved_db_path = db_path or Path("data/jarvis.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[misc]
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

        # Forward events to WebSocket clients (skip events originating from WS itself)
        async def ws_forwarder(event: Event) -> None:
            if event.source == "websocket":
                return
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
        await event_bus.publish(Event(topic="system.shutdown", source="kernel", payload={}))
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
