"""FastAPI application — entry point for the KALI kernel."""

import json
import logging
import sys
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
from kernel.skill_executor import SkillExecutor
from kernel.sandbox.network_proxy import NetworkProxy
from kernel.sandbox.permission_enforcer import PermissionEnforcer
from kernel.voice.pipeline import VoicePipeline
from kernel.builder.intent_classifier import classify_intent
from kernel.builder.skill_generator import generate_skill
from kernel.builder.agent_generator import generate_agent
from kernel.builder.safety_gate import check_code
from kernel.builder.deployer import deploy_skill, deploy_agent
from kernel.builder.wizard import create_wizard
from kernel.catalog.package import pack as pack_agent, get_package_info
from kernel.catalog.client import CatalogClient
from kernel.catalog.installer import install_package

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

    # When running as a PyInstaller bundle, bundled data lives under _MEIPASS;
    # the writable data dir is next to the .exe itself.
    _bundle_dir = Path(getattr(sys, "_MEIPASS", ""))
    _is_frozen = hasattr(sys, "_MEIPASS")
    if _is_frozen:
        _exe_dir = Path(sys.executable).parent
        _default_config = _bundle_dir / "config" / "kali.yaml"
        _default_agents = _bundle_dir / "agents"
        _default_db = _exe_dir / "data" / "kali.db"
    else:
        _default_config = Path("config/kali.yaml")
        _default_agents = Path("agents")
        _default_db = Path("data/kali.db")

    resolved_config_path = config_path or _default_config
    resolved_agents_dir = agents_dir or _default_agents
    resolved_db_path = db_path or _default_db

    # Ensure writable data directory exists (important for frozen exe)
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[misc]
        # Initialize all components
        event_bus = EventBus()
        config_manager = ConfigManager(resolved_config_path)
        config_manager.load()
        plugin_registry = PluginRegistry(resolved_agents_dir)
        plugin_registry.discover()

        # Initialize skill executor
        skill_executor = SkillExecutor(data_dir=resolved_db_path.parent)
        for manifest in plugin_registry.list_skills():
            skill_dir = resolved_agents_dir / manifest.name
            try:
                skill_executor.load_skill(skill_dir)
                logger.info("Loaded skill: %s", manifest.name)
            except Exception as e:
                logger.warning("Failed to load skill %s: %s", manifest.name, e)
        app.state.skill_executor = skill_executor

        # Create sandbox components
        network_proxy = NetworkProxy()
        permission_enforcer = PermissionEnforcer()
        app.state.network_proxy = network_proxy
        app.state.permission_enforcer = permission_enforcer

        agent_runtime = AgentRuntime(
            registry=plugin_registry,
            agents_dir=resolved_agents_dir,
            event_bus=event_bus,
            enforcer=permission_enforcer,
            network_proxy=network_proxy,
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

        # Register skill schedules
        for name in skill_executor.list_skills():
            info = skill_executor.get_skill_info(name)
            if info:
                config = info.get("config", {})
                cron = None
                if "schedule" in config and "cron" in config["schedule"]:
                    cron = config["schedule"]["cron"]
                elif "reminders" in config and config["reminders"].get("enabled"):
                    interval_h = config["reminders"].get("interval_hours")
                    if interval_h:
                        cron = f"0 */{interval_h} * * *"
                if cron:
                    try:
                        scheduler.register_cron(name, cron, topic=f"skill.{name}.trigger")
                        logger.info("Registered cron for skill %s: %s", name, cron)
                    except ValueError as e:
                        logger.warning("Invalid cron for skill %s: %s", name, e)

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

        # Auto-load essential agents (built-in = auto-approved)
        builtin_agents = {"system", "weather", "tasks", "calendar"}
        for agent_name in builtin_agents:
            try:
                await agent_runtime.load_agent(agent_name)
                manifest = plugin_registry.get(agent_name)
                if manifest and permission_enforcer:
                    manifest.permissions.user_approved = True
                    permission_enforcer.register_agent(agent_name, manifest)
                logger.info("Auto-loaded agent: %s", agent_name)
            except Exception:
                logger.warning("Failed to auto-load agent: %s", agent_name)

        app.state.builtin_agents = builtin_agents

        catalog_client = CatalogClient()
        app.state.catalog_client = catalog_client

        # Load TTS models (Silero + RVC ONNX) — in-process, no separate server needed
        try:
            import asyncio
            from kernel.voice.tts_engine import load_models, is_loaded
            await asyncio.to_thread(load_models)
            logger.info("TTS engine loaded in-process")
        except Exception:
            logger.warning("TTS engine not available (will use cloud fallbacks)")

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
            s = request.app.state
            await s.agent_runtime.load_agent(name)
            # Auto-approve built-in agents on manual load too
            if name in s.builtin_agents:
                manifest = s.plugin_registry.get(name)
                if manifest and s.permission_enforcer:
                    manifest.permissions.user_approved = True
                    s.permission_enforcer.register_agent(name, manifest)
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

    @app.post("/agents/{name}/execute")
    async def execute_agent_tool(name: str, request: Request) -> dict[str, Any]:
        """Execute an agent tool/action directly."""
        body = await request.json()
        action = body.get("action", "")
        args = body.get("args", {})

        runtime = request.app.state.agent_runtime

        try:
            status = await runtime.get_status(name)
        except Exception:
            status = None

        if not status or status.get("status") != "running":
            try:
                await runtime.load_agent(name)
                # Auto-approve built-in agents loaded on demand
                s = request.app.state
                if name in s.builtin_agents:
                    manifest = s.plugin_registry.get(name)
                    if manifest and s.permission_enforcer:
                        manifest.permissions.user_approved = True
                        s.permission_enforcer.register_agent(name, manifest)
            except Exception as e:
                return {"error": f"Agent '{name}' not available: {e}"}

        try:
            result = await runtime.dispatch(name, action, args)
            return result
        except PermissionError as e:
            logger.warning("Agent permission denied: %s/%s: %s", name, action, e)
            return {"error": f"Permission denied: {e}"}
        except Exception as e:
            logger.warning("Agent execute failed: %s/%s: %s", name, action, e)
            return {"error": str(e)}

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
                        f"Погода в {result.get('city', 'Москве')}: "
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
                        f"Сейчас {result.get('time', '')}, "
                        f"{result.get('weekday', '')}"
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
                        f"Задачи: {result.get('done', 0)} из {result.get('total', 0)} выполнено, "
                        f"{result.get('pending', 0)} в ожидании"
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
                    "response": "Таймер фокусировки запущен. 25 минут. Удачной работы, сэр.",
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

        # Default: direct OpenAI call (no voice pipeline dependency)
        try:
            import openai

            client = openai.AsyncOpenAI()
            llm_config = s.config_manager.config.llm
            messages = s.memory.get_context() + [
                {"role": "user", "content": text},
            ]

            completion = await client.chat.completions.create(
                model=llm_config.cloud_model,
                messages=messages,
            )

            response_text = (completion.choices[0].message.content or "").strip()
            if response_text:
                s.memory.add_turn("user", text)
                s.memory.add_turn("assistant", response_text)
            return {
                "response": response_text or "Не удалось получить ответ.",
                "source": f"llm-{llm_config.cloud_provider}",
            }
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            return {
                "response": f"LLM ошибка: {e}",
                "source": "system",
            }

    @app.get("/skills")
    async def list_skills_route(request: Request) -> list[dict[str, Any]]:
        """List all loaded skills."""
        executor = request.app.state.skill_executor
        return [info for name in executor.list_skills() if (info := executor.get_skill_info(name)) is not None]

    @app.post("/skills/{name}/{action}")
    async def execute_skill_route(name: str, action: str, request: Request) -> Any:
        """Execute a skill action."""
        body: dict[str, Any] = {}
        if request.headers.get("content-type") == "application/json":
            body = await request.json()
        try:
            result = await request.app.state.skill_executor.execute(name, action, body)
            return result
        except ValueError as e:
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": str(e)}, status_code=404)

    @app.post("/tts")
    async def text_to_speech(request: Request) -> Any:
        """Convert text to speech — in-process Silero + RVC ONNX with cloud fallbacks."""
        from fastapi.responses import Response, StreamingResponse
        import asyncio
        import io
        import os

        body = await request.json()
        text = body.get("text", "")
        language = body.get("language")
        if not text:
            return {"error": "No text provided"}

        # Priority 1: In-process Silero + RVC ONNX (no HTTP round-trip)
        try:
            from kernel.voice.tts_engine import (
                generate_audio, audio_to_wav_bytes, is_loaded, load_models,
            )
            if not is_loaded():
                logger.info("TTS not loaded yet, attempting lazy init...")
                await asyncio.to_thread(load_models)
            if is_loaded():
                audio, sr = await asyncio.to_thread(generate_audio, text, language)
                wav_bytes = audio_to_wav_bytes(audio, sr)
                return Response(content=wav_bytes, media_type="audio/wav")
        except Exception as e:
            logger.warning("Local TTS failed: %s, trying cloud fallbacks", e)

        # Priority 2: ElevenLabs (cloned voice, cloud)
        el_key = os.environ.get("ELEVENLABS_API_KEY")
        el_voice = os.environ.get("ELEVENLABS_VOICE_ID")

        if el_key and el_voice:
            try:
                from elevenlabs.client import ElevenLabs

                client = ElevenLabs(api_key=el_key)
                audio_generator = client.text_to_speech.convert(
                    voice_id=el_voice,
                    text=text,
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128",
                )
                audio_bytes = b"".join(audio_generator)
                return StreamingResponse(
                    io.BytesIO(audio_bytes),
                    media_type="audio/mpeg",
                    headers={"Content-Disposition": "inline"},
                )
            except Exception as e:
                logger.warning("ElevenLabs TTS failed: %s", e)

        # Priority 3: OpenAI TTS (onyx voice, cloud fallback)
        try:
            import openai

            client = openai.OpenAI()
            response = client.audio.speech.create(
                model="tts-1",
                voice="onyx",
                input=text,
                response_format="mp3",
                speed=1.05,
            )
            audio_bytes = response.content
            return StreamingResponse(
                io.BytesIO(audio_bytes),
                media_type="audio/mpeg",
                headers={"Content-Disposition": "inline"},
            )
        except Exception as e:
            logger.warning("TTS failed: %s", e)
            return {"error": str(e)}

    @app.post("/synthesize")
    async def synthesize_endpoint(request: Request) -> Any:
        """Alias for /tts — backward compat with TTS client and frontend."""
        return await text_to_speech(request)

    @app.get("/health/tts")
    async def tts_health() -> dict[str, Any]:
        """TTS engine health check."""
        try:
            from kernel.voice.tts_engine import is_loaded
            loaded = is_loaded()
        except Exception:
            loaded = False
        return {
            "status": "ok" if loaded else "not loaded",
            "engine": "silero-v4 + onnx-rvc-v2",
        }

    @app.post("/builder/classify")
    async def builder_classify(request: Request) -> dict[str, Any]:
        """Classify user request as skill or agent."""
        body = await request.json()
        text = body.get("text", "")
        result = classify_intent(text)
        return {
            "type": result.type,
            "template": result.template,
            "confidence": result.confidence,
            "reason": result.reason,
        }

    @app.post("/builder/create-skill")
    async def builder_create_skill(request: Request) -> dict[str, Any]:
        """Generate and deploy a skill."""
        body = await request.json()
        name = body["name"]
        template = body["template"]
        description = body.get("description", name)
        config = body.get("config", {})

        skill_dir = generate_skill(
            name=name,
            template=template,
            description=description,
            config=config,
            agents_dir=resolved_agents_dir,
        )
        return await deploy_skill(
            skill_dir,
            request.app.state.skill_executor,
            getattr(request.app.state, "scheduler", None),
        )

    @app.post("/builder/create-agent")
    async def builder_create_agent(request: Request) -> dict[str, Any]:
        """Generate, validate, and deploy an agent."""
        import shutil

        body = await request.json()
        name = body["name"]
        description = body["description"]
        tools = body.get("tools", [])
        apis = body.get("apis", [])

        agent_dir = generate_agent(
            name=name,
            description=description,
            tools=tools,
            apis=apis,
            agents_dir=resolved_agents_dir,
        )
        if not agent_dir:
            return {"status": "error", "message": "Agent generation failed"}

        # Safety gate
        code = (agent_dir / "agent.py").read_text()
        safety = check_code(code)
        if not safety.safe:
            shutil.rmtree(agent_dir)
            return {"status": "unsafe", "issues": safety.issues}

        return await deploy_agent(
            agent_dir,
            request.app.state.plugin_registry,
            request.app.state.agent_runtime,
        )

    @app.get("/catalog/search")
    async def catalog_search(request: Request, q: str = "", category: str = "") -> dict[str, Any]:
        """Search catalog — local agents first, then cloud."""
        client = request.app.state.catalog_client
        local = await client.local_search(q, resolved_agents_dir) if q else []
        cloud = await client.search(q, category=category or None) if q else []
        local_names = {r["name"] for r in local}
        results = local + [c for c in cloud if c.get("name") not in local_names]
        return {"results": results, "count": len(results)}

    @app.post("/catalog/pack/{name}")
    async def catalog_pack(name: str) -> dict[str, Any]:
        """Pack agent/skill into .kali-agent file."""
        agent_dir = resolved_agents_dir / name
        if not agent_dir.exists():
            return {"error": f"Agent '{name}' not found"}
        try:
            Path("exports").mkdir(exist_ok=True)
            output = pack_agent(agent_dir, Path("exports") / f"{name}.kali-agent")
            return {"status": "packed", "path": str(output)}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/catalog/install")
    async def catalog_install(request: Request) -> dict[str, Any]:
        """Install from .kali-agent file."""
        from fastapi.responses import JSONResponse

        body = await request.json()
        path = Path(body.get("path", ""))
        if path.suffix != ".kali-agent":
            return JSONResponse({"error": "Must be a .kali-agent file"}, status_code=400)
        if not path.exists():
            return {"error": f"File not found: {path}"}
        result = await install_package(
            path,
            agents_dir=resolved_agents_dir,
            skill_executor=getattr(request.app.state, "skill_executor", None),
            plugin_registry=getattr(request.app.state, "plugin_registry", None),
            agent_runtime=getattr(request.app.state, "agent_runtime", None),
        )
        return result

    @app.get("/catalog/info")
    async def catalog_info(path: str = "") -> dict[str, Any]:
        """Get package info without installing."""
        p = Path(path)
        if not p.exists():
            return {"error": "File not found"}
        try:
            return get_package_info(p)
        except Exception as e:
            return {"error": str(e)}

    @app.get("/catalog/trending")
    async def catalog_trending(request: Request) -> dict[str, Any]:
        """Trending — cloud packages, or local agents as fallback."""
        client = request.app.state.catalog_client
        cloud = await client.trending()
        if cloud:
            return {"results": cloud}
        local = await client.local_search("", resolved_agents_dir)
        return {"results": local}

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=3005, log_level="info")
