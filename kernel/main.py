"""FastAPI application — entry point for the KALI kernel."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from kernel import __version__
from kernel.agent_builder import AgentBuilder
from kernel.agent_runtime.dispatcher import ToolDispatcher
from kernel.agent_runtime.runtime import AgentRuntime
from kernel.briefing import BriefingService
from kernel.budget import BudgetManager
from kernel.config_manager import ConfigManager
from kernel.database import Database
from kernel.event_bus import EventBus
from kernel.focus import FocusTimer
from kernel.memory import ConversationMemory
from kernel.models import Event, WSMessage
from kernel.notifications import NotificationManager
from kernel.plugin_registry import PluginRegistry
from kernel.routines import RoutineManager
from kernel.scheduler import Scheduler
from kernel.voice.pipeline import VoicePipeline

logger = logging.getLogger(__name__)


def create_app(
    config_path: Path | None = None,
    agents_dir: Path | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    All state is stored on app.state — no module-level globals.

    Args:
        config_path: Path to kali.yaml config file. Defaults to config/kali.yaml.
        agents_dir: Path to agents directory. Defaults to agents/.
        db_path: Path to SQLite database file. Defaults to data/kali.db.

    Returns:
        Configured FastAPI application instance.
    """
    load_dotenv()

    resolved_config_path = config_path or Path("config/kali.yaml")
    resolved_agents_dir = agents_dir or Path("agents")
    resolved_db_path = db_path or Path("data/kali.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[misc]
        # Initialize all components
        event_bus = EventBus()
        config_manager = ConfigManager(resolved_config_path)
        config_manager.load()
        plugin_registry = PluginRegistry(resolved_agents_dir)
        plugin_registry.discover()
        agent_runtime = AgentRuntime(
            registry=plugin_registry,
            agents_dir=resolved_agents_dir,
            event_bus=event_bus,
        )
        tool_dispatcher = ToolDispatcher(
            runtime=agent_runtime,
            registry=plugin_registry,
        )
        app.state.agent_runtime = agent_runtime
        app.state.tool_dispatcher = tool_dispatcher
        database = Database(resolved_db_path)
        await database.initialize()
        await database.prune_old_conversations()
        memory = ConversationMemory(database)
        notifications = NotificationManager(event_bus)
        app.state.memory = memory
        app.state.notifications = notifications
        briefing = BriefingService(event_bus)
        budget_mgr = BudgetManager(event_bus)
        focus_timer = FocusTimer(event_bus)
        routine_mgr = RoutineManager(event_bus)
        agent_builder = AgentBuilder(event_bus)
        app.state.briefing = briefing
        app.state.budget = budget_mgr
        app.state.focus = focus_timer
        app.state.routines = routine_mgr
        app.state.agent_builder = agent_builder
        scheduler = Scheduler(event_bus, config_manager.config.schedule)
        scheduler.start()

        # Voice pipeline (optional — only if dependencies available)
        try:
            voice_pipeline = VoicePipeline(
                event_bus=event_bus,
                voice_config=config_manager.config.voice,
                llm_config=config_manager.config.llm,
                tools=plugin_registry.get_all_tools(),
            )
            app.state.voice_pipeline = voice_pipeline
            logger.info("Voice pipeline initialized")
        except Exception:
            logger.warning("Voice pipeline not available")
            app.state.voice_pipeline = None

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

        # Auto-load essential agents
        for agent_name in ["system", "weather", "tasks"]:
            try:
                await agent_runtime.load_agent(agent_name)
                logger.info("Auto-loaded agent: %s", agent_name)
            except Exception:
                logger.warning("Failed to auto-load agent: %s", agent_name)

        logger.info("KALI kernel started (v%s)", __version__)
        yield

        # Graceful shutdown
        await event_bus.publish(Event(topic="system.shutdown", source="kernel", payload={}))
        await agent_runtime.shutdown_all()
        await scheduler.stop()
        await database.close()
        logger.info("KALI kernel stopped")

    app = FastAPI(title="KALI Kernel", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    @app.get("/voice/status")
    async def voice_status(request: Request) -> dict[str, Any]:
        vp = request.app.state.voice_pipeline
        if vp is None:
            return {"available": False}
        return {
            "available": True,
            "state": vp.state.value,
            "mode": vp.mode,
        }

    @app.post("/voice/start")
    async def voice_start(request: Request) -> dict[str, str]:
        vp = request.app.state.voice_pipeline
        if vp is None:
            return {"status": "error", "message": "Voice pipeline not available"}
        vp.load_models()
        await vp.start()
        return {"status": "started"}

    @app.post("/voice/stop")
    async def voice_stop(request: Request) -> dict[str, str]:
        vp = request.app.state.voice_pipeline
        if vp is None:
            return {"status": "error", "message": "Voice pipeline not available"}
        await vp.stop()
        return {"status": "stopped"}

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

    @app.get("/agents/running")
    async def running_agents(request: Request) -> list[dict[str, Any]]:
        return request.app.state.agent_runtime.list_agents()

    @app.post("/agents/{name}/load")
    async def load_agent(name: str, request: Request) -> dict[str, str]:
        try:
            await request.app.state.agent_runtime.load_agent(name)
            return {"status": "loaded", "agent": name}
        except ValueError as e:
            return {"status": "error", "message": str(e)}

    @app.post("/agents/{name}/unload")
    async def unload_agent(name: str, request: Request) -> dict[str, str]:
        await request.app.state.agent_runtime.unload_agent(name)
        return {"status": "unloaded", "agent": name}

    @app.get("/agents/{name}/status")
    async def agent_status(name: str, request: Request) -> dict[str, Any]:
        return await request.app.state.agent_runtime.get_status(name)

    @app.post("/notifications/send")
    async def send_notification(request: Request) -> dict[str, str]:
        from kernel.notifications import Notification

        body = await request.json()
        notif = Notification(
            title=body.get("title", "KALI"),
            message=body.get("message", ""),
            priority=body.get("priority", "normal"),
        )
        await request.app.state.notifications.send(notif)
        return {"status": "sent"}

    @app.get("/notifications/pending")
    async def pending_notifications(request: Request) -> list[dict]:  # type: ignore[type-arg]
        return [
            {
                "title": n.title,
                "message": n.message,
                "priority": n.priority,
                "timestamp": n.timestamp,
            }
            for n in request.app.state.notifications.get_pending()
        ]

    @app.get("/briefing/morning")
    async def morning_briefing(request: Request) -> dict[str, Any]:
        data: dict[str, Any] = {}  # TODO(#42): collect from agents when running
        text = await request.app.state.briefing.generate_morning_briefing(data)
        return {"text": text}

    @app.post("/budget/goal")
    async def set_budget_goal(request: Request) -> dict[str, Any]:
        body = await request.json()
        return request.app.state.budget.set_goal(body["category"], body["limit"])

    @app.get("/budget/goals")
    async def get_budget_goals(request: Request) -> dict[str, Any]:
        return request.app.state.budget.get_goals()

    @app.post("/budget/expense")
    async def log_budget_expense(request: Request) -> dict[str, Any]:
        body = await request.json()
        return await request.app.state.budget.log_expense(body["amount"], body["category"])

    @app.post("/focus/start")
    async def start_focus(request: Request) -> dict[str, Any]:
        body = await request.json()
        return await request.app.state.focus.start(
            body.get("duration_minutes", 25), body.get("label", "")
        )

    @app.post("/focus/stop")
    async def stop_focus(request: Request) -> dict[str, Any]:
        return await request.app.state.focus.stop()

    @app.get("/focus/status")
    async def focus_status(request: Request) -> dict[str, Any]:
        return request.app.state.focus.get_status()

    @app.get("/routines")
    async def list_routines(request: Request) -> dict[str, Any]:
        return request.app.state.routines.list_routines()

    @app.post("/routines/{name}/execute")
    async def execute_routine(name: str, request: Request) -> dict[str, Any]:
        return await request.app.state.routines.execute(name)

    @app.post("/agents/create")
    async def create_custom_agent(request: Request) -> dict[str, Any]:
        body = await request.json()
        template = body.get("template")
        if template:
            return request.app.state.agent_builder.create_from_template(
                body["name"], body.get("description", ""), template
            )
        return request.app.state.agent_builder.create_agent(
            name=body["name"],
            description=body.get("description", ""),
            tools=body.get("tools", []),
            action_code=body.get("code", ""),
            permissions=body.get("permissions"),
        )

    @app.get("/agents/custom")
    async def list_custom_agents(request: Request) -> list[dict[str, Any]]:
        return request.app.state.agent_builder.list_custom_agents()

    @app.delete("/agents/custom/{name}")
    async def delete_custom_agent(name: str, request: Request) -> dict[str, Any]:
        return request.app.state.agent_builder.delete_agent(name)

    @app.post("/chat")
    async def chat(request: Request) -> dict[str, Any]:
        """Process a chat message through LLM or agents."""
        body = await request.json()
        text = body.get("text", "")
        if not text:
            return {"response": "Empty message", "source": "system"}

        s = request.app.state
        text_lower = text.lower()

        # Direct agent commands (simple keyword matching for v1)
        if any(w in text_lower for w in ["weather", "погода", "температура"]):
            try:
                result = await s.agent_runtime.dispatch(
                    "weather", "get_weather", {"city": "Moscow"},
                )
                return {
                    "response": (
                        f"Weather in {result.get('city', 'Moscow')}: "
                        f"{result.get('temperature_c')}°C, "
                        f"{result.get('condition', '')}"
                    ),
                    "source": "weather-agent",
                    "data": result,
                }
            except Exception:
                pass

        if any(w in text_lower for w in ["time", "время", "час"]):
            try:
                result = await s.agent_runtime.dispatch("system", "get_time", {})
                return {
                    "response": (
                        f"Current time: {result.get('time', '')} "
                        f"({result.get('weekday', '')})"
                    ),
                    "source": "system-agent",
                    "data": result,
                }
            except Exception:
                pass

        if any(w in text_lower for w in ["task", "задач", "todo"]):
            try:
                result = await s.agent_runtime.dispatch(
                    "tasks", "get_summary", {},
                )
                return {
                    "response": (
                        f"Tasks: {result.get('done', 0)}/{result.get('total', 0)} "
                        f"done, {result.get('pending', 0)} pending"
                    ),
                    "source": "tasks-agent",
                    "data": result,
                }
            except Exception:
                pass

        if any(w in text_lower for w in ["brief", "утро", "morning", "день"]):
            try:
                briefing_text = await s.briefing.generate_morning_briefing({})
                return {"response": briefing_text, "source": "briefing"}
            except Exception:
                pass

        if any(
            w in text_lower
            for w in ["focus", "фокус", "pomodoro", "помодоро", "таймер"]
        ):
            try:
                await s.focus.start(25, "work")
                return {
                    "response": "Focus timer started: 25 minutes. Stay focused!",
                    "source": "focus-timer",
                }
            except Exception:
                pass

        if any(
            w in text_lower
            for w in ["budget", "бюджет", "расход", "потратил"]
        ):
            try:
                goals = s.budget.get_goals()
                if goals:
                    parts = [
                        f"{cat}: ${info['spent']}/{info['limit']}"
                        for cat, info in goals.items()
                    ]
                    return {
                        "response": f"Budget: {', '.join(parts)}",
                        "source": "budget",
                    }
                return {
                    "response": "No budget goals set. Use /budget/goal to set one.",
                    "source": "budget",
                }
            except Exception:
                pass

        # Default: route through LLM
        try:
            from kernel.llm_router import LLMRequest

            llm_request = LLMRequest(
                text=text,
                context=s.memory.get_context(),
                available_tools=s.plugin_registry.get_all_tools(),
            )
            llm_response = await s.voice_pipeline._llm.route(llm_request)
            s.memory.add_turn("user", text)
            s.memory.add_turn("assistant", llm_response.text)
            return {
                "response": llm_response.text,
                "source": f"llm-{llm_response.provider_used}",
            }
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            return {
                "response": (
                    f"I heard: \"{text}\". LLM error: {e}. "
                    "Check your API key in .env file."
                ),
                "source": "system",
            }

    return app
