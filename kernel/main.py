"""FastAPI application — entry point for the KALI kernel."""

import json
import logging
import os
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from kernel import __version__
from kernel.routers._shared import (
    _get_sandbox,
    _mask_key,
    _save_env,
)
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
from kernel.models import ConfigSchema, Event, WSMessage
from kernel.notifications import NotificationManager
from kernel.plugin_registry import PluginRegistry
from kernel.routines import RoutineManager
from kernel.scheduler import Scheduler
from kernel.skill_executor import SkillExecutor
from kernel.sandbox.network_proxy import NetworkProxy
from kernel.sandbox.permission_enforcer import PermissionEnforcer
from kernel.voice.pipeline import VoicePipeline
from kernel.builder.wizard import create_wizard
from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore
from kernel.catalog.client import CatalogClient

logger = logging.getLogger(__name__)

# Safe-by-default CORS allow-list: the legitimate KALI app origins only.
# NEVER use "*" here — wildcard origins combined with allow_credentials=True is a
# browser-attack surface on localhost. An explicit list keeps credentials valid.
#   - tauri://localhost            : production Tauri WebView origin
#   - http(s)://tauri.localhost    : Windows WebView2 Tauri origin (see CSP)
#   - http://localhost:1420        : Vite dev server / Tauri devUrl (ui/vite.config.ts)
#   - http://127.0.0.1:1420        : same dev server via loopback IP
# Override/extend via the KALI_CORS_ORIGINS env (comma-separated).
_DEFAULT_CORS_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


def _cors_origins() -> list[str]:
    """Resolve allowed CORS origins from env or Desktop/dev defaults."""
    raw = os.environ.get("KALI_CORS_ORIGINS", "")
    if raw.strip():
        origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
        if origins:
            return origins
    return list(_DEFAULT_CORS_ORIGINS)


def _resolve_host() -> str:
    """Resolve the bind host for the Python backend.

    Safe-by-default: binds loopback (127.0.0.1) so dev/other launches are not
    exposed to the LAN. Set ``KALI_HOST=0.0.0.0`` to explicitly opt into LAN
    exposure (the shipped desktop already injects ``KALI_HOST=127.0.0.1``).

    Note: the Rust :3006 LAN channel (mobile companion) is a separate concern,
    secured with a per-install token in WS-4 — not by this default.

    Returns:
        The host interface to bind, from ``KALI_HOST`` or ``"127.0.0.1"``.
    """
    return os.environ.get("KALI_HOST", "127.0.0.1")


async def _build_daily_briefing(s: Any, is_ru: bool) -> str:
    """Build a personalized daily briefing from all active agents."""
    import time as _time

    hour = _time.localtime().tm_hour
    parts: list[str] = []

    # Time-appropriate greeting
    if is_ru:
        if 5 <= hour < 12:
            parts.append("Доброе утро, сэр.")
        elif 12 <= hour < 17:
            parts.append("Добрый день, сэр.")
        elif 17 <= hour < 22:
            parts.append("Добрый вечер, сэр.")
        else:
            parts.append("Доброй ночи, сэр.")
    else:
        if 5 <= hour < 12:
            parts.append("Good morning, sir.")
        elif 12 <= hour < 17:
            parts.append("Good afternoon, sir.")
        elif 17 <= hour < 22:
            parts.append("Good evening, sir.")
        else:
            parts.append("Good night, sir.")

    # Weather
    try:
        wx = await s.agent_runtime.dispatch("weather", "get_weather", {"city": "Moscow"})
        temp = wx.get("temperature_c", "?")
        cond = wx.get("condition", "")
        if is_ru:
            _WRU = {"Clear sky": "ясно", "Partly cloudy": "облачно", "Overcast": "пасмурно",
                    "Moderate rain": "дождь", "Light rain": "небольшой дождь", "Heavy rain": "ливень",
                    "Light snow": "снег", "Fog": "туман", "Thunderstorm": "гроза", "Drizzle": "морось",
                    "Slight rain": "слабый дождь", "Mainly clear": "ясно"}
            cond = _WRU.get(cond, cond)
            parts.append(f"На улице {temp}°C, {cond}.")
        else:
            parts.append(f"Weather: {temp}°C, {cond}.")
    except Exception:
        logger.debug("briefing: weather section unavailable", exc_info=True)

    # Tasks
    try:
        tasks = await s.agent_runtime.dispatch("tasks", "get_summary", {})
        total = tasks.get("total", 0)
        done = tasks.get("done", 0)
        pending = tasks.get("pending", 0)
        if total > 0:
            if is_ru:
                parts.append(f"Задачи: {done} из {total} выполнено, {pending} в ожидании.")
            else:
                parts.append(f"Tasks: {done} of {total} done, {pending} pending.")
        else:
            parts.append("Нет активных задач." if is_ru else "No active tasks.")
    except Exception:
        logger.debug("briefing: tasks section unavailable", exc_info=True)

    # Calendar
    try:
        cal = await s.agent_runtime.dispatch("calendar", "get_events", {"date": "today"})
        events = cal.get("events", [])
        if events:
            next_ev = events[0]
            title = next_ev.get("title", "")
            start = next_ev.get("start", "")
            if is_ru:
                parts.append(f"Ближайшее событие: {title} в {start}. Всего {len(events)} событий сегодня.")
            else:
                parts.append(f"Next event: {title} at {start}. {len(events)} events today.")
        else:
            parts.append("Календарь на сегодня пуст." if is_ru else "Calendar is clear today.")
    except Exception:
        logger.debug("briefing: calendar section unavailable", exc_info=True)

    # Active agents count
    try:
        running = [a for a in s.agent_runtime.list_agents() if a.get("status") == "running"]
        count = len(running)
        if is_ru:
            parts.append(f"{count} агентов активно.")
        else:
            parts.append(f"{count} agents active.")
    except Exception:
        logger.debug("briefing: agents section unavailable", exc_info=True)

    # Skills
    try:
        skill_count = len(s.skill_executor.list_skills())
        if skill_count > 0:
            if is_ru:
                parts.append(f"{skill_count} навыков загружено.")
            else:
                parts.append(f"{skill_count} skills loaded.")
    except Exception:
        logger.debug("briefing: skills section unavailable", exc_info=True)

    # Final
    if is_ru:
        parts.append("Чем могу помочь?")
    else:
        parts.append("How can I help you?")

    return " ".join(parts)


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
    # When running as a PyInstaller bundle, bundled data lives under _MEIPASS;
    # the writable data dir is next to the .exe itself.
    _bundle_dir = Path(getattr(sys, "_MEIPASS", ""))
    _is_frozen = hasattr(sys, "_MEIPASS")
    if _is_frozen:
        _exe_dir = Path(sys.executable).parent
        # Writable data goes to %APPDATA%\KALI (Program Files is read-only)
        _appdata = Path(os.environ.get("APPDATA", _exe_dir)) / "KALI"
        _appdata.mkdir(parents=True, exist_ok=True)
        # Load .env from AppData (user's keys) → exe dir → cwd
        load_dotenv(_appdata / ".env")
        load_dotenv(_exe_dir / ".env")
        _default_config = _bundle_dir / "config" / "kali.yaml"
        _default_agents = _bundle_dir / "agents"
        _default_db = _appdata / "kali.db"
    else:
        load_dotenv()
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
        import asyncio

        # Initialize all components
        event_bus = EventBus()
        config_manager = ConfigManager(resolved_config_path)
        config_manager.load()
        plugin_registry = PluginRegistry(resolved_agents_dir)
        plugin_registry.discover()

        # Initialize skill executor. Only agents with a skill.yaml are YAML-template
        # skills (tracker/reminder/etc.); SKILL.md-only agents are served by the
        # plugin_registry, so skip them here instead of logging a misleading warning.
        skill_executor = SkillExecutor(data_dir=resolved_db_path.parent)
        for manifest in plugin_registry.list_skills():
            skill_dir = resolved_agents_dir / manifest.name
            if not (skill_dir / "skill.yaml").exists():
                continue
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
        
        from kernel.long_term_memory import LongTermMemory
        lt_memory = LongTermMemory(database, config_manager.config.llm)
        app.state.long_term_memory = lt_memory
        
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
        # Phase 3 Chunk 8: skip Python pipeline init when voice.engine="rust"
        # so the Rust backend's native /voice/* routes own the lifecycle.
        # `app.state.voice_pipeline = None` keeps any direct hits on Python's
        # /voice/* endpoints returning 503 — UI dispatcher already routes
        # them to Rust (RUST_ENDPOINTS allow-list).
        if config_manager.config.voice.engine != "python":
            logger.info(
                "Voice pipeline disabled in Python (voice.engine=%s) — Rust backend authoritative",
                config_manager.config.voice.engine,
            )
            app.state.voice_pipeline = None
        else:
            try:
                voice_pipeline = VoicePipeline(
                    event_bus=event_bus,
                    voice_config=config_manager.config.voice,
                    llm_config=config_manager.config.llm,
                    tools=plugin_registry.get_all_tools(),
                    app_state=app.state,
                )
                app.state.voice_pipeline = voice_pipeline
                logger.info("Voice pipeline initialized")
                
                from kernel.voice.remote_pipeline import RemoteVoicePipeline
                remote_pipeline = RemoteVoicePipeline(
                    event_bus=event_bus,
                    voice_config=config_manager.config.voice,
                    llm_config=config_manager.config.llm,
                    tools=plugin_registry.get_all_tools(),
                    app_state=app.state,
                )
                app.state.remote_pipeline = remote_pipeline
                logger.info("Remote Voice pipeline initialized")

                # Pre-import torch ONCE, in a worker thread, awaited, BEFORE the
                # auto-start task and the TTS/STT prewarm spawn their own load
                # threads. Two subtleties in the frozen bundle:
                #   1) `import torch` on the MAIN thread crashes in torch's custom-op
                #      registration (pyi_rth_inspect mishandles the main-thread frame);
                #      the same import on a worker thread is fine.
                #   2) concurrent first-imports of torch from multiple load threads
                #      race ("partially initialized module 'torch'").
                # Importing it here via to_thread (single, awaited) satisfies both:
                # worker-thread import (no crash) + serialized (no race); later loads
                # then see torch already imported and skip the racey first-import.
                if hasattr(sys, "_MEIPASS"):
                    def _preimport_torch() -> None:
                        import torch  # noqa: F401

                    try:
                        await asyncio.to_thread(_preimport_torch)
                        logger.info("torch pre-imported (single-threaded)")
                    except Exception:
                        logger.exception("torch pre-import failed")

                # Voice pipeline — auto-start only if user opted in via config.
                # Default OFF: user toggles via UI (privacy + battery + RAM friendly).
                voice_cfg = config_manager.config.voice
                if voice_cfg.auto_start and voice_cfg.mode != "off":
                    async def _voice_bg_start() -> None:
                        try:
                            import asyncio as _aio_vp
                            await _aio_vp.to_thread(voice_pipeline.load_models)
                            await voice_pipeline.start()
                            logger.info("Voice pipeline auto-started (mode=%s, wake_word=%s)",
                                       voice_cfg.mode, voice_cfg.wake_word)
                        except Exception as e:
                            logger.warning("Voice pipeline auto-start failed: %s", e)
                    asyncio.create_task(_voice_bg_start())
                else:
                    logger.info("Voice pipeline ready (mode=%s, auto_start=%s) — waiting for /voice/start",
                               voice_cfg.mode, voice_cfg.auto_start)
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
        # Strong references to background auto-speak tasks. Without a retained
        # ref the GC can cancel a task mid-speech (asyncio fire-and-forget trap).
        app.state._speak_tasks: set[asyncio.Task[None]] = set()
        # Retained refs to model-download failure-event publishes. A weakly
        # referenced publish (ensure_future + drop) can be GC-cancelled before
        # it runs, so the failure event would never reach the bus.
        app.state._download_publish_tasks: set[asyncio.Task[None]] = set()

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
        event_bus.subscribe("canvas.*", ws_forwarder)
        event_bus.subscribe("schedule.*", ws_forwarder)
        event_bus.subscribe("system.*", ws_forwarder)

        # Scheduled skills: when the scheduler fires `skill.{name}.trigger`, run
        # the skill's periodic action and deliver anything user-facing. Without
        # this subscriber the cron event had NO consumer, so timed skills fired
        # into the void (core-loop 3b).
        _SKILL_TRIGGER_ACTION = {"reminder": "check", "monitor": "check", "notifier": "notify"}

        async def _on_skill_trigger(event: Event) -> None:
            parts = event.topic.split(".")
            if len(parts) < 3 or parts[0] != "skill" or parts[-1] != "trigger":
                return
            name = ".".join(parts[1:-1])
            executor = app.state.skill_executor
            info = executor.get_skill_info(name)
            if not info:
                return
            action = _SKILL_TRIGGER_ACTION.get(info.get("template", ""))
            if action is None:
                return
            try:
                result = await executor.execute(name, action)
            except Exception:
                logger.exception("Scheduled skill '%s' (%s) failed", name, action)
                return
            if isinstance(result, dict) and result.get("should_fire") is False:
                return  # the skill decided not to fire right now
            message = ""
            if isinstance(result, dict):
                message = result.get("message") or result.get("alert") or ""
            if message:
                from kernel.notifications import Notification

                await app.state.notifications.send(
                    Notification(
                        title=info.get("display_name", name),
                        message=str(message),
                        source=f"skill.{name}",
                    )
                )

        event_bus.subscribe("skill.*", _on_skill_trigger)

        # Phase 2: forward relayed topics to the Rust backend on :3006 so it
        # can fan out to UI WebSocket clients. Fire-and-forget — Rust being
        # absent during dev does not affect Python behaviour.
        from kernel.rust_bridge import RustEventBridge, subscribe_to_bus

        rust_bridge = RustEventBridge()
        subscribe_to_bus(rust_bridge, event_bus)
        app.state.rust_bridge = rust_bridge

        # In frozen (PyInstaller) mode, patch AgentRuntime to use in-process
        # protocol instead of subprocess — prevents fork bomb from sys.executable.
        if hasattr(sys, "_MEIPASS"):
            from kernel.agent_runtime.protocols.inprocess import InProcessProtocol
            _original_create_protocol = agent_runtime._create_protocol

            def _frozen_create_protocol(manifest):  # type: ignore[no-untyped-def]
                if manifest.protocol == "native":
                    script = agent_runtime._agents_dir / manifest.name / "agent.py"
                    return InProcessProtocol(agent_name=manifest.name, script_path=script)
                return _original_create_protocol(manifest)

            agent_runtime._create_protocol = _frozen_create_protocol  # type: ignore[method-assign]
            logger.info("Frozen mode: agents will run in-process (no subprocess)")

        # Auto-load essential agents (built-in = auto-approved)
        builtin_agents = {"system", "weather", "tasks", "calendar", "live-canvas"}
        for agent_name in builtin_agents:
            try:
                await agent_runtime.load_agent(agent_name)
                manifest = plugin_registry.get(agent_name)
                if manifest and permission_enforcer:
                    manifest.permissions.user_approved = True
                    permission_enforcer.register_agent(agent_name, manifest)
                logger.info("Auto-loaded agent: %s", agent_name)
            except Exception as e:
                logger.warning("Failed to auto-load agent: %s - %s", agent_name, str(e), exc_info=True)

        app.state.builtin_agents = builtin_agents

        # Restore persisted consent (M2.2): a sticky revoke survives restart, so
        # a previously-revoked agent (even an auto-approved built-in) is NOT
        # re-approved here; an approved one is restored.
        try:
            from datetime import datetime, timezone
            for _ag, _status in (await database.get_all_consents()).items():
                _m = plugin_registry.get(_ag)
                if not _m:
                    continue
                if _status == "revoked":
                    _m.permissions.user_approved = False
                elif _status == "approved":
                    _m.permissions.user_approved = True
                    _m.permissions.approval_timestamp = datetime.now(timezone.utc)
                    permission_enforcer.register_agent(_ag, _m)
        except Exception as _e:
            logger.warning("Consent restore failed: %s", _e)

        catalog_client = CatalogClient()
        app.state.catalog_client = catalog_client

        app.state.builder_flow = BuilderFlow(
            session_store=SessionStore(),
            agents_dir=resolved_agents_dir,
            skill_executor=app.state.skill_executor,
            scheduler=app.state.scheduler,
            plugin_registry=app.state.plugin_registry,
        )

        # Voice-engine prewarm — load F5-TTS + Whisper STT eagerly so the
        # first /tts/speak (wizard question) and /voice/transcribe (user
        # utterance) don't pay the ~5s cold-load cost at the worst possible
        # moment for the voice-builder pilot.
        #
        # Subsumes the previous `_tts_bg_load()` background task (deleted)
        # which raced with this prewarm in default config (auto_start=true)
        # and could double-load F5 weights → GPU OOM on smaller cards.
        # Sequential `await` here is intentional: startup blocks until both
        # engines are warm so the first user gesture sees a hot cache.
        #
        # Best-effort: each block has its own try/except → logger.warning;
        # startup never aborts on prewarm failure (on-demand load paths
        # in /tts/speak and get_or_create_stt still work as fallback).
        #
        # Tests skip via `KALI_SKIP_PREWARM=1` (set in tests/conftest.py)
        # to avoid loading real ML models per-test fixture.
        if os.environ.get("KALI_SKIP_PREWARM"):
            logger.info("Voice prewarm skipped (KALI_SKIP_PREWARM set)")
        else:
            try:
                from kernel.voice.tts_router import is_loaded, load_models

                if not is_loaded():
                    logger.info("TTS prewarm: loading F5 models...")
                    await asyncio.to_thread(load_models)
                    logger.info("TTS prewarm: ready")

                # CUDA warmup: the first real synth pays ~2x for kernel
                # compilation (6.3 s vs 2.9 s for the same-size text in the
                # live log) — a throwaway micro-synth in the background moves
                # that cost off the user's first answer. F5 module called
                # directly so a warmup failure can never trigger the router's
                # cloud (ElevenLabs) fallback.
                from kernel.voice.tts_router import PROVIDER_F5, get_provider

                if get_provider() == PROVIDER_F5:
                    async def _warmup_synth() -> None:
                        try:
                            from kernel.voice import tts_engine_f5
                            await asyncio.to_thread(
                                tts_engine_f5.generate_audio, "Готов."
                            )
                            logger.info("TTS warmup synth: done (first answer is hot)")
                        except Exception as e:
                            logger.warning("TTS warmup synth failed (non-fatal): %s", e)

                    app.state._tts_warmup_task = asyncio.create_task(_warmup_synth())
            except Exception as e:
                import traceback as _tb
                logger.warning(
                    "TTS prewarm failed (non-fatal): %s\n%s", e, _tb.format_exc()
                )

            # STT prewarm runs in the background so lifespan yields immediately:
            # first-run Whisper download (~480MB) must not block /health. The
            # on-demand load path (get_or_create_stt in /tts and /voice/transcribe)
            # covers requests that arrive before the model is warm.
            async def _prewarm_stt() -> None:
                try:
                    from kernel.voice.transcribe_helper import get_or_create_stt

                    logger.info("STT prewarm: loading Whisper model...")
                    await asyncio.to_thread(get_or_create_stt, app.state)
                    logger.info("STT prewarm: ready")
                except Exception as e:
                    logger.warning("STT prewarm failed (non-fatal): %s", e)

            # Strong reference prevents the task from being GC-cancelled.
            app.state._prewarm_task = asyncio.create_task(_prewarm_stt())

        logger.info("KALI kernel started (v%s)", __version__)
        yield

        # Graceful shutdown
        await event_bus.publish(Event(topic="system.shutdown", source="kernel", payload={}))
        await agent_runtime.shutdown_all()
        await scheduler.stop()
        await database.close()
        await rust_bridge.close()
        logger.info("KALI kernel stopped")

    app = FastAPI(title="KALI Kernel", version=__version__, lifespan=lifespan)
    # Resolved paths for routers/_shared helpers — computed pre-lifespan, needed
    # by endpoints that previously closed over create_app() locals.
    app.state.agents_dir = resolved_agents_dir
    app.state.db_path = resolved_db_path
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
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

    @app.get("/dashboard")
    async def get_dashboard(request: Request) -> dict[str, Any]:
        """Live dashboard for the mobile app — computed from real agents, not
        stored placeholders. Each widget degrades to a neutral «—» (never a
        fake number) when its agent has no data, so the UI never shows a
        fabricated value as if it were real.
        """
        s = request.app.state
        rt = s.agent_runtime

        async def _safe(agent: str, action: str, args: dict[str, Any]) -> dict[str, Any] | None:
            try:
                return await rt.dispatch(agent, action, args)
            except Exception:
                return None

        # Weather — real, via the (Cyrillic-capable) weather agent.
        city = os.environ.get("KALI_DEFAULT_CITY", "Москва")
        wx = await _safe("weather", "get_weather", {"city": city})
        if wx and wx.get("temperature_c") is not None:
            weather = {"temp": f"{round(wx['temperature_c']):+d}°C",
                       "condition": wx.get("condition", "")}
        else:
            weather = {"temp": "—", "condition": ""}

        # Tasks — real, via the tasks agent summary.
        ts = await _safe("tasks", "get_summary", {})
        if ts:
            tasks = {"active": ts.get("pending", 0),
                     "completed": ts.get("done", 0),
                     "subtitle": f"{ts.get('done', 0)} выполнено сегодня"}
        else:
            tasks = {"active": 0, "completed": 0, "subtitle": "нет задач"}

        # Spending today — real, via life-dashboard. Shown in the «budget»
        # slot the mobile reads, but labeled honestly as spending.
        life = await _safe("life-dashboard", "get_daily_summary", {})
        if life and life.get("total_spending"):
            spending = {"amount": f"₽{life['total_spending']:,}".replace(",", " "),
                        "status": "потрачено сегодня"}
        else:
            spending = {"amount": "—", "status": "нет трат сегодня"}

        return {"weather": weather, "budget": spending, "tasks": tasks}

    @app.get("/config")
    async def get_config(request: Request) -> dict[str, Any]:
        return request.app.state.config_manager.config.model_dump()

    @app.patch("/config")
    async def patch_config(request: Request):
        """Apply an RFC 7396 JSON Merge Patch to the YAML config.

        Semantics:
          - Body is merged into the current config via merge_patch().
          - A `null` value at a known top-level section (voice, llm, schedule,
            server) is rejected with 422 — this path exists only to guard
            against accidental wipes; use an explicit reset endpoint if that
            becomes a real need.
          - The merged result is validated against ConfigSchema. On failure the
            client receives 422 and the on-disk file is NOT modified.
          - On success the file is saved atomically (tempfile + os.replace)
            with a `.bak` sibling containing the prior contents.
          - After write the config is reloaded and `config.changed` is
            published on the event bus so live subscribers can react.
        """
        from fastapi.responses import JSONResponse
        from pydantic import ValidationError

        from kernel.config_manager import merge_patch

        try:
            body = await request.json()
        except Exception as exc:
            return JSONResponse({"error": f"invalid JSON: {exc}"}, status_code=400)

        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "request body must be a JSON object"},
                status_code=400,
            )

        _GUARDED_SECTIONS = {"voice", "llm", "schedule", "server"}
        nulled = [k for k in _GUARDED_SECTIONS if k in body and body[k] is None]
        if nulled:
            return JSONResponse(
                {
                    "error": "cannot null a top-level section via PATCH",
                    "sections": nulled,
                },
                status_code=422,
            )

        cm: ConfigManager = request.app.state.config_manager
        current = cm.config.model_dump()
        merged = merge_patch(current, body)

        try:
            validated = ConfigSchema.model_validate(merged)
        except ValidationError as exc:
            return JSONResponse(
                {"error": "invalid config", "detail": exc.errors()},
                status_code=422,
            )

        saved = cm.save(validated)

        await request.app.state.event_bus.publish(
            Event(
                topic="config.changed",
                source="kernel",
                payload={"sections": sorted(body.keys())},
            )
        )

        return saved.model_dump()

    @app.post("/llm/test")
    async def llm_test(request: Request) -> dict[str, Any]:
        """Live validation of an API key for a provider.

        Makes one minimal request to the provider's chat endpoint. Returns
        {ok: True} on success, {ok: False, error: str} on failure.
        Used by the onboarding flow to validate keys before persisting.
        """
        body = await request.json()
        provider = (body.get("provider") or "").lower()
        api_key = body.get("api_key")
        if not provider or not api_key:
            return {"ok": False, "error": "provider and api_key are required"}

        try:
            if provider == "openai":
                import openai
                client = openai.AsyncOpenAI(api_key=api_key)
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                return {"ok": bool(resp.choices)}
            if provider == "anthropic":
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=api_key)
                resp = await client.messages.create(
                    model="claude-3-5-haiku-latest",
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                return {"ok": bool(resp.content)}
            if provider == "google":
                import httpx
                url = (
                    "https://generativelanguage.googleapis.com/v1beta/models"
                    f"?key={api_key}"
                )
                async with httpx.AsyncClient(timeout=10.0) as http:
                    r = await http.get(url)
                    if r.status_code == 200:
                        return {"ok": True}
                    return {"ok": False, "error": f"HTTP {r.status_code}"}
            if provider == "deepseek":
                import httpx
                async with httpx.AsyncClient(timeout=15.0) as http:
                    r = await http.post(
                        "https://api.deepseek.com/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 1,
                        },
                    )
                    if r.status_code == 200:
                        return {"ok": True}
                    return {"ok": False, "error": f"HTTP {r.status_code}"}
            return {"ok": False, "error": f"unknown provider: {provider}"}
        except Exception as e:
            logger.info("llm_test failed: %s", e)
            return {"ok": False, "error": str(e)}

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
                    if msg.type in ("ui.command", "voice.state", "voice.audio_stream"):
                        await s.event_bus.publish(
                            Event(
                                topic=msg.type,
                                source="websocket",
                                payload=msg.data,
                            )
                        )
                        # We don't need to ACK audio streams to save bandwidth
                        if msg.type == "ui.command":
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

    @app.get("/canvas/widgets")
    async def get_canvas_widgets(request: Request) -> dict[str, Any]:
        """Return current live-canvas widgets for initial UI render."""
        runtime = request.app.state.agent_runtime
        try:
            status = await runtime.get_status("live-canvas")
            if not status or status.get("status") != "running":
                return {"widgets": [], "count": 0}
            result = await runtime.dispatch("live-canvas", "list_widgets", {})
            return result
        except Exception:
            return {"widgets": [], "count": 0}

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

    # --- Sandbox inspection endpoints ---

    @app.get("/sandbox/health")
    async def sandbox_health(request: Request) -> dict[str, Any]:
        """Inspect the active sandbox backend."""
        sandbox = _get_sandbox(request.app)
        return await sandbox.health()

    @app.get("/sandbox/audit")
    async def sandbox_audit(
        request: Request,
        agent: str = "", status: str = "",
        hours: int = 24, limit: int = 100,
    ) -> dict[str, Any]:
        """Recent audit log entries (defaults: last 24h, 100 rows)."""
        _get_sandbox(request.app)  # ensure audit_log exists
        import time as _t
        since = _t.time() - max(1, hours) * 3600
        rows = request.app.state.sandbox_audit.query(
            agent=agent or None,
            status=status or None,
            since=since,
            limit=max(1, min(limit, 1000)),
        )
        return {"results": rows, "count": len(rows), "since_hours": hours}

    @app.get("/sandbox/stats")
    async def sandbox_stats(request: Request, hours: int = 24) -> dict[str, Any]:
        """Aggregate dispatch stats per agent over the last N hours."""
        _get_sandbox(request.app)
        import time as _t
        since = _t.time() - max(1, hours) * 3600
        stats = request.app.state.sandbox_audit.stats_by_agent(since=since)
        return {"results": stats, "count": len(stats), "since_hours": hours}

    @app.get("/settings")
    async def get_settings(request: Request) -> dict[str, Any]:
        """Get current settings."""
        import os
        return {
            "llm": {
                "provider": os.environ.get("LLM_PROVIDER", "openai"),
                "openai_key": _mask_key(os.environ.get("OPENAI_API_KEY", "")),
                "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "anthropic_key": _mask_key(os.environ.get("ANTHROPIC_API_KEY", "")),
                "anthropic_model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                "google_key": _mask_key(os.environ.get("GOOGLE_API_KEY", "")),
                "google_model": os.environ.get("GOOGLE_MODEL", "gemini-3.1-pro"),
                "deepseek_key": _mask_key(os.environ.get("DEEPSEEK_API_KEY", "")),
                "deepseek_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v3.2"),
            },
            "tts": {
                "provider": os.environ.get("KALI_TTS_PROVIDER", "auto"),
                "elevenlabs_voice_id": os.environ.get("ELEVENLABS_VOICE_ID", ""),
                "elevenlabs_key": _mask_key(os.environ.get("ELEVENLABS_API_KEY", "")),
            },
            "voice": {
                "wake_word": getattr(getattr(getattr(request.app.state, "config_manager", None), "config", None), "voice", None) and request.app.state.config_manager.config.voice.wake_word or os.environ.get("WAKE_WORD", "jarvis"),
                "mode": os.environ.get("VOICE_MODE", "wake_word"),
                "stt_model": os.environ.get("STT_MODEL", "base"),
            },
            "language": os.environ.get("KALI_LANGUAGE", "ru"),
            # Onboarding gate: frontend reads this to decide whether to show
            # the welcome flow. Stored in .env as KALI_ONBOARDING_COMPLETED.
            "onboarding_completed": os.environ.get("KALI_ONBOARDING_COMPLETED", "").lower() == "true",
        }

    @app.post("/settings")
    async def update_settings(request: Request) -> dict[str, Any]:
        """Update settings. Persists API keys to .env file."""
        import os
        body = await request.json()

        updates: dict[str, str] = {}
        if "openai_key" in body and body["openai_key"] and not body["openai_key"].startswith("sk-***"):
            os.environ["OPENAI_API_KEY"] = body["openai_key"]
            updates["OPENAI_API_KEY"] = body["openai_key"]
        if "anthropic_key" in body and body["anthropic_key"] and not body["anthropic_key"].startswith("sk-***"):
            os.environ["ANTHROPIC_API_KEY"] = body["anthropic_key"]
            updates["ANTHROPIC_API_KEY"] = body["anthropic_key"]
        if "google_key" in body and body["google_key"] and not body["google_key"].startswith("AI***"):
            os.environ["GOOGLE_API_KEY"] = body["google_key"]
            updates["GOOGLE_API_KEY"] = body["google_key"]
        if "deepseek_key" in body and body["deepseek_key"] and not body["deepseek_key"].startswith("sk-***"):
            os.environ["DEEPSEEK_API_KEY"] = body["deepseek_key"]
            updates["DEEPSEEK_API_KEY"] = body["deepseek_key"]
        if "openai_model" in body:
            os.environ["OPENAI_MODEL"] = body["openai_model"]
            updates["OPENAI_MODEL"] = body["openai_model"]
        if "anthropic_model" in body:
            os.environ["ANTHROPIC_MODEL"] = body["anthropic_model"]
            updates["ANTHROPIC_MODEL"] = body["anthropic_model"]
        if "google_model" in body:
            os.environ["GOOGLE_MODEL"] = body["google_model"]
            updates["GOOGLE_MODEL"] = body["google_model"]
        if "deepseek_model" in body:
            os.environ["DEEPSEEK_MODEL"] = body["deepseek_model"]
            updates["DEEPSEEK_MODEL"] = body["deepseek_model"]
        if "provider" in body:
            os.environ["LLM_PROVIDER"] = body["provider"]
            updates["LLM_PROVIDER"] = body["provider"]
        if "language" in body:
            os.environ["KALI_LANGUAGE"] = body["language"]
            updates["KALI_LANGUAGE"] = body["language"]
        if "onboarding_completed" in body:
            value = "true" if body["onboarding_completed"] else "false"
            os.environ["KALI_ONBOARDING_COMPLETED"] = value
            updates["KALI_ONBOARDING_COMPLETED"] = value

        # Agent credentials (Telegram/Notion/Todoist/smart-home). Only env
        # names in the registry whitelist are accepted, so a request can't set
        # arbitrary environment variables. Masked values (read-back) are
        # skipped so a re-save of the settings form doesn't clobber a real key.
        from kernel.agent_keys import ALLOWED_AGENT_KEYS
        for key in ALLOWED_AGENT_KEYS:
            if key in body and body[key] and "***" not in str(body[key]):
                os.environ[key] = str(body[key])
                updates[key] = str(body[key])

        if updates:
            _save_env(updates)

        return {"status": "updated", "keys": list(updates.keys())}

    # Domain routers (2026-07-13 split) — imported here, not at module top,
    # so routers may import kernel.routers._shared without an import cycle.
    # Registration order is inter-module-safe: extracted paths are exact
    # (no parametrized shadowing against the remaining inline routes).
    from kernel.routers import agents as agents_router
    from kernel.routers import builder as builder_router
    from kernel.routers import catalog as catalog_router
    from kernel.routers import chat as chat_router
    from kernel.routers import skills as skills_router
    from kernel.routers import voice as voice_router

    app.include_router(chat_router.router)
    app.include_router(voice_router.router)
    app.include_router(skills_router.router)
    app.include_router(catalog_router.router)
    app.include_router(agents_router.router)
    app.include_router(builder_router.router)

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # CRITICAL: must be first line — prevents fork bomb in PyInstaller --onefile
    import multiprocessing
    multiprocessing.freeze_support()

    import uvicorn

    # Enable debug logging for voice pipeline components
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("kernel.voice").setLevel(logging.DEBUG)

    app = create_app()
    uvicorn.run(
        app,
        host=_resolve_host(),
        port=int(os.environ.get("KALI_PORT", "3005")),
        log_level="info",
    )
