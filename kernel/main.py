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
    _get_skills_catalog,
    _get_skills_registry,
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
from kernel.builder.intent_classifier import classify_intent
from kernel.builder.skill_generator import generate_skill
from kernel.builder.agent_generator import generate_agent
from kernel.builder.safety_gate import check_code
from kernel.builder.deployer import deploy_skill, deploy_agent
from kernel.builder.wizard import create_wizard
from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore
from kernel.catalog.package import pack as pack_agent, get_package_info
from kernel.catalog.client import CatalogClient
from kernel.catalog.installer import install_package

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

    @app.get("/agents")
    async def list_agents(request: Request) -> list[dict[str, Any]]:
        return [a.model_dump() for a in request.app.state.plugin_registry.list_registered()]

    @app.get("/agents/tools")
    async def list_tools(request: Request) -> list[dict[str, Any]]:
        return request.app.state.plugin_registry.get_all_tools()

    @app.get("/agents/{name}/capabilities")
    async def agent_capabilities(name: str, request: Request) -> dict[str, Any]:
        """Plain-language capability disclosure for the consent-disclosure flow.

        Returns the agent's manifest capabilities classified into RU labels and
        risk tiers (see kernel.capabilities). Disclosure only — does not change
        any permission/enforcement behavior. Unknown agents return an empty,
        non-sensitive result (never 404) so the UI never crashes.
        """
        from kernel.capabilities import describe_capabilities

        manifest = request.app.state.plugin_registry.get(name)
        caps = manifest.capabilities if manifest else []
        return {"name": name, **describe_capabilities(caps)}

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

    @app.get("/agents/running")
    async def running_agents(request: Request) -> list[dict[str, Any]]:
        return request.app.state.agent_runtime.list_agents()

    @app.get("/agents/config-status")
    async def agents_config_status() -> dict[str, Any]:
        """Per-agent credential status so the UI can show «Нужна настройка».

        «running» means the process is up; this says whether the keys it needs
        are actually present — the difference between «Работает» and a button
        that does nothing.
        """
        from kernel.agent_keys import all_agents_config_status
        return all_agents_config_status()

    async def _approve_agent(s: Any, name: str, *, explicit: bool = False) -> None:
        """Grant runtime permission to an agent the user enabled.

        Explicit user actions (enabling via «Включить» / «Разрешить») always
        approve and clear any prior revoke. Implicit approvals (a direct tool
        call) respect a STICKY revoke: a revoked agent stays unapproved until
        the user explicitly re-enables it — M2.2 semantics A. Consent is
        persisted so it (and a revoke) survives a restart.
        """
        from datetime import datetime, timezone

        manifest = s.plugin_registry.get(name)
        if not (manifest and s.permission_enforcer):
            return
        db = getattr(s, "database", None)
        if not explicit and db is not None and await db.get_consent(name) == "revoked":
            return  # sticky revoke — wait for an explicit re-enable
        manifest.permissions.user_approved = True
        manifest.permissions.approval_timestamp = datetime.now(timezone.utc)
        s.permission_enforcer.register_agent(name, manifest)
        if db is not None:
            await db.set_consent(name, "approved")

    @app.post("/agents/{name}/load")
    async def load_agent(name: str, request: Request) -> dict[str, str]:
        try:
            s = request.app.state
            await s.agent_runtime.load_agent(name)
            await _approve_agent(s, name, explicit=True)
            return {"status": "loaded", "agent": name}
        except ValueError as e:
            return {"status": "error", "message": str(e)}

    @app.post("/agents/{name}/unload")
    async def unload_agent(name: str, request: Request) -> dict[str, str]:
        await request.app.state.agent_runtime.unload_agent(name)
        return {"status": "unloaded", "agent": name}

    @app.post("/agents/{name}/revoke")
    async def revoke_agent(name: str, request: Request) -> dict[str, str]:
        """Revoke a previously-granted consent (sticky — M2.2 semantics A).

        Clears approval in-memory (the enforcer shares the PermissionSet object,
        so calls are denied immediately) and persists the revoke so it survives
        a restart and is not undone by an implicit approve-on-execute.
        """
        s = request.app.state
        manifest = s.plugin_registry.get(name)
        if manifest:
            manifest.permissions.user_approved = False
        db = getattr(s, "database", None)
        if db is not None:
            await db.set_consent(name, "revoked")
        return {"status": "revoked", "agent": name}

    @app.get("/agents/consents")
    async def list_consents(request: Request) -> dict[str, str]:
        """Persisted per-agent consent state — ``{name: 'approved'|'revoked'}``.

        Lets the UI reflect durable consent (M2.2): which agents have a granted,
        revocable consent vs. which were revoked, so a revoke / re-enable control
        shows real state across reloads and restarts. Empty if never recorded.
        """
        db = getattr(request.app.state, "database", None)
        if db is None:
            return {}
        return await db.get_all_consents()

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
            except Exception as e:
                return {"error": f"Agent '{name}' not available: {e}"}

        # A direct tool call implicitly approves a not-yet-revoked agent so an
        # already-running-but-unapproved agent doesn't 403. A sticky revoke
        # (M2.2) is respected: a revoked agent stays denied until re-enabled.
        await _approve_agent(request.app.state, name, explicit=False)

        # Route through SandboxBackend — adds permission + rate limit + audit
        sandbox = _get_sandbox(request.app)
        from kernel.sandbox.backend import DispatchRequest
        dispatch_result = await sandbox.dispatch(
            DispatchRequest(
                agent_name=name, action=action, args=args,
                caller=body.get("caller", "user"),
                request_id=body.get("request_id", ""),
            )
        )

        if dispatch_result.ok:
            # Unwrap the single-key "result" envelope for backward compat
            payload = dispatch_result.result or {}
            if set(payload.keys()) == {"result"}:
                payload = payload["result"] if isinstance(payload["result"], dict) else payload

            # Live Canvas: push widget updates to UI via EventBus → WebSocket
            if name == "live-canvas" and action in ("render_widget", "clear_canvas"):
                await request.app.state.event_bus.publish(
                    Event(
                        topic="canvas.update",
                        source="live-canvas",
                        payload={"action": action, **payload},
                    )
                )

            return payload

        # Map denial reason → HTTP status for API clients that care
        from fastapi.responses import JSONResponse
        http_status = 200
        if dispatch_result.denied_reason == "rate_limit":
            http_status = 429
        elif dispatch_result.denied_reason == "permission":
            http_status = 403

        return JSONResponse(
            {
                "error": dispatch_result.error or "dispatch failed",
                "denied_reason": dispatch_result.denied_reason,
                "agent": name,
                "action": action,
                "duration_ms": dispatch_result.duration_ms,
            },
            status_code=http_status,
        )

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

    @app.post("/builder/start")
    async def builder_start(request: Request) -> Any:
        """Start a builder flow from a natural-language request.

        Expects JSON body with ``request`` (str). Returns session metadata
        including the first clarifying question and total wizard steps.
        """
        from fastapi.responses import JSONResponse

        body = await request.json()
        text = (body.get("request") or "").strip()
        if not text:
            return JSONResponse({"error": "request must be non-empty"}, status_code=400)

        try:
            return request.app.state.builder_flow.start(text)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            logger.exception("builder/start failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/builder/extract")
    async def builder_extract(request: Request) -> Any:
        """A4 fast-path: single-shot LLM extraction over the wizard schema.

        Tries to populate every wizard answer from the user utterance in
        one LLM call. On full match returns the complete spec; on partial
        match returns a session pre-populated up to the first missing
        field plus the next question; on failure / invalid template /
        LLM unavailable, silently falls back to `/builder/start` shape.
        """
        from fastapi.responses import JSONResponse
        from kernel.builder.extractor import extract_spec

        body = await request.json()
        text = (body.get("request") or "").strip()
        if not text:
            return JSONResponse({"error": "request must be non-empty"}, status_code=400)

        try:
            return extract_spec(
                request=text,
                session_store=request.app.state.builder_flow._store,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            logger.exception("/builder/extract failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/builder/answer")
    async def builder_answer(request: Request) -> Any:
        """Record an answer in the active builder wizard.

        Expects JSON body with ``session_id`` (str) and ``answer`` (str).
        Returns next question dict while wizard is in progress, or a preview
        dict once all questions are answered.
        """
        from fastapi.responses import JSONResponse
        from kernel.builder.session_store import SessionNotFound

        body = await request.json()
        sid = body.get("session_id", "")
        text = (body.get("answer") or "").strip()
        if not sid or not text:
            return JSONResponse(
                {"error": "session_id and answer required"}, status_code=400
            )

        try:
            return request.app.state.builder_flow.answer(sid, text)
        except SessionNotFound:
            return JSONResponse(
                {"error": "session not found or expired"}, status_code=404
            )

    @app.post("/builder/deploy")
    async def builder_deploy(request: Request) -> Any:
        """Materialise and deploy the skill built in this session.

        Expects JSON body with ``session_id`` (str). The wizard must be
        complete (all answers provided) before deploying.
        """
        from fastapi.responses import JSONResponse
        from kernel.builder.session_store import SessionNotFound

        body = await request.json()
        sid = body.get("session_id", "")
        if not sid:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        try:
            return await request.app.state.builder_flow.deploy(sid)
        except SessionNotFound:
            return JSONResponse({"error": "session not found"}, status_code=404)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/builder/cancel")
    async def builder_cancel(request: Request) -> Any:
        """Abort an in-flight builder session.

        Expects JSON body with ``session_id`` (str). No-op if the session is
        already gone; always returns ``{"status": "cancelled"}``.
        """
        from fastapi.responses import JSONResponse

        body = await request.json()
        sid = body.get("session_id", "")
        if not sid:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        request.app.state.builder_flow.cancel(sid)
        return {"status": "cancelled"}

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

    @app.get("/catalog/community")
    async def catalog_community(request: Request, q: str = "") -> dict[str, Any]:
        """Merged «Сообщество» feed: Supabase ``approved`` UGC ∪ GitHub curated.

        Returns one deduped, source-tagged card list (``source`` ∈
        ``ugc``/``curated``/``local``) so the tab renders a single card surface.
        UGC cards carry the §4 social counts (likes/ratings) + creator handle;
        curated cards carry the GitHub install handle (``source_id``+``name``).

        Graceful degradation (preserved contract): when Supabase is
        unconfigured/offline the UGC list is ``[]`` (``CatalogClient.browse``
        already degrades), so the feed becomes curated ∪ locally-installed with
        NO error wall. A failed GitHub refresh likewise yields the cached/empty
        curated set rather than raising.

        Args:
            q: Optional case-insensitive substring filter over name/description.
        """
        from kernel.catalog.merge import merge_community

        client = request.app.state.catalog_client

        # Supabase approved UGC (search when a query is given, else browse all).
        ugc = await (client.search(q) if q else client.browse())

        # GitHub curated shelf — refresh the curated source so a cold start has
        # data; refresh_source returns cached/[] on a network failure (no raise).
        catalog = _get_skills_catalog(app)
        curated_dicts: list[dict[str, Any]] = []
        try:
            catalog.refresh_source("kali")
            entries = catalog.list_by_source("kali")
            if q:
                qlow = q.lower()
                entries = [
                    e for e in entries
                    if qlow in e.name.lower() or qlow in e.description.lower()
                ]
            curated_dicts = [e.to_dict() for e in entries]
        except Exception as exc:  # noqa: BLE001 — degrade to no curated set
            logger.warning("community: curated refresh failed: %s", exc)

        # Locally-installed agents — the offline fallback so the tab is never
        # empty/error-walled when Supabase is down.
        local = await client.local_search(q, resolved_agents_dir)

        # Enrich UGC cards with live social counts (best-effort; missing → zeros).
        social_by_slug: dict[str, dict[str, Any]] = {}
        for row in ugc:
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            try:
                social_by_slug[slug] = await client.get_social(slug)
            except Exception:  # noqa: BLE001 — a missing aggregate degrades to zeros
                continue

        results = merge_community(
            ugc, curated_dicts, local, social_by_slug=social_by_slug
        )
        return {"results": results, "count": len(results)}

    @app.post("/catalog/community/install")
    async def catalog_community_install(request: Request) -> dict[str, Any]:
        """Install a Supabase UGC skill by slug (download bundle → live install).

        Body: ``{"slug": "<skills.slug>"}``. Routes through
        ``CatalogClient.install_skill`` (Storage download → AST safety gate →
        register into the live runtime) and records an install attribution.
        Degrades to ``{"status": "unconfigured"}`` when Supabase is offline.
        Curated GitHub cards use ``/skills/install`` (source_id+name) instead.
        """
        from fastapi.responses import JSONResponse

        body = await request.json()
        slug = (body or {}).get("slug", "").strip()
        if not slug:
            return JSONResponse(
                status_code=400, content={"status": "error", "reason": "slug_required"}
            )
        client = request.app.state.catalog_client
        result = await client.install_skill(
            slug,
            agents_dir=resolved_agents_dir,
            plugin_registry=getattr(request.app.state, "plugin_registry", None),
            skill_executor=getattr(request.app.state, "skill_executor", None),
            agent_runtime=getattr(request.app.state, "agent_runtime", None),
        )
        # Best-effort attribution (no PII) — never block the install on a counter.
        if result.get("status") not in {"unconfigured", "error"}:
            try:
                await client.record_install(slug)
            except Exception:  # noqa: BLE001 — attribution is best-effort
                pass
        return result

    # --- Community account (magic-link sign-in, WS-3 Task 3.3/3.5) ---
    # KALI's OWN account: email → Supabase magic-link OTP. NEVER Google/Apple
    # OAuth (§7 anti-pivot). Anonymous browse/install/like need no account; only
    # rate/comment are account-gated — these routes surface the honest sign-in
    # prompt the UI shows when a signed-out write returns "sign-in required".

    @app.get("/community/account")
    async def community_account(request: Request) -> dict[str, Any]:
        """Report the current KALI account session (signed-in id, if any).

        Returns ``{"signed_in": bool, "account_id": str | None}`` — used by the
        community UI to decide whether a rate/comment needs the sign-in prompt.
        Degrades to signed-out when Supabase is offline.
        """
        identity = request.app.state.catalog_client.identity
        account_id = identity.current_account_id()
        return {"signed_in": account_id is not None, "account_id": account_id}

    @app.post("/community/account/magic-link")
    async def community_magic_link(request: Request) -> dict[str, Any]:
        """Send a magic-link / OTP email (Supabase ``sign_in_with_otp``).

        Body: ``{"email": "<address>"}``. Returns the identity layer result
        VERBATIM (``{"status": "sent"}`` / ``"unconfigured"`` / ``"error"``) so
        the UI shows honest status — never a fake success. NOT OAuth.
        """
        from fastapi.responses import JSONResponse

        body = await request.json()
        email = (body or {}).get("email", "").strip()
        if not email:
            return JSONResponse(
                status_code=400, content={"status": "error", "reason": "email_required"}
            )
        return request.app.state.catalog_client.identity.request_magic_link(email)

    @app.post("/community/account/verify")
    async def community_verify(request: Request) -> dict[str, Any]:
        """Exchange the emailed OTP for a session (Supabase ``verify_otp``).

        Body: ``{"email": "<address>", "token": "<code>"}``. Returns the identity
        result verbatim (``{"status": "signed_in"}`` / ``"error"`` / ...).
        """
        from fastapi.responses import JSONResponse

        body = await request.json()
        email = (body or {}).get("email", "").strip()
        token = (body or {}).get("token", "").strip()
        if not email or not token:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "reason": "email_and_token_required"},
            )
        return request.app.state.catalog_client.identity.verify_magic_link(email, token)

    @app.post("/community/account/sign-out")
    async def community_sign_out(request: Request) -> dict[str, Any]:
        """Sign out of the KALI account + clear the persisted session."""
        return request.app.state.catalog_client.identity.sign_out()

    # --- Community social layer (like / rate / comment, WS-3 Task 3.4) ---
    # Each route returns the CatalogClient result VERBATIM so an honest
    # "sign-in required" (rate/comment when signed out) reaches the UI as such,
    # never a fake success. Likes are anon (device-id); rate/comment are
    # account-gated inside the client. All degrade gracefully when offline.

    @app.post("/catalog/{slug}/like")
    async def catalog_like(slug: str, request: Request) -> dict[str, Any]:
        """Like a skill as the anonymous local device (idempotent, no sign-in)."""
        return await request.app.state.catalog_client.like(slug)

    @app.delete("/catalog/{slug}/like")
    async def catalog_unlike(slug: str, request: Request) -> dict[str, Any]:
        """Remove this device's like from a skill."""
        return await request.app.state.catalog_client.unlike(slug)

    @app.post("/catalog/{slug}/rating")
    async def catalog_rating(slug: str, request: Request) -> dict[str, Any]:
        """Set this account's 1-5 star rating (account-gated; honest sign-in)."""
        body = await request.json()
        return await request.app.state.catalog_client.set_rating(
            slug, body.get("stars")
        )

    @app.post("/catalog/{slug}/comment")
    async def catalog_comment(slug: str, request: Request) -> dict[str, Any]:
        """Post a comment (account-gated; defaults to pending moderation)."""
        body = await request.json()
        return await request.app.state.catalog_client.post_comment(
            slug, body.get("body", "")
        )

    @app.get("/catalog/{slug}/comments")
    async def catalog_comments(slug: str, request: Request) -> dict[str, Any]:
        """List a skill's approved comments (newest first)."""
        comments = await request.app.state.catalog_client.list_comments(slug)
        return {"comments": comments}

    @app.get("/catalog/{slug}/social")
    async def catalog_social(slug: str, request: Request) -> dict[str, Any]:
        """Aggregate a skill's social signals (likes + ratings + viewer state)."""
        return await request.app.state.catalog_client.get_social(slug)

    # --- Community moderation lifecycle (WS-3 Task 3.7, §5C) ---
    # The report route is PUBLIC (the report button — anon or signed-in). The
    # status-transition + queue routes are MODERATION-ONLY: gated behind
    # `_require_moderator`, which checks an `X-Moderator-Token` header against the
    # KALI_MODERATOR_TOKEN env/config flag and returns 403 otherwise. This is the
    # auth SEAM only — the real moderation authority is a human gate (Vasily
    # reviews at MVP), and the privileged CatalogClient transitions run with the
    # Supabase service_role key in production (never the public anon client).

    def _require_moderator(request: Request):
        """Return a 403 JSONResponse when the caller is not an authorized moderator.

        Returns None when authorized (the route proceeds). The check is a simple
        shared-secret seam: the `X-Moderator-Token` header must equal the
        `KALI_MODERATOR_TOKEN` env value. When no token is configured the endpoint
        is CLOSED (always 403) — moderation never defaults to open. This is the
        auth seam only; the real authority is a human gate (Vasily at MVP).
        """
        from fastapi.responses import JSONResponse

        expected = os.environ.get("KALI_MODERATOR_TOKEN")
        provided = request.headers.get("x-moderator-token")
        if not expected or not provided or provided != expected:
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "moderator_only"},
            )
        return None

    @app.post("/catalog/{slug}/report")
    async def catalog_report(slug: str, request: Request) -> dict[str, Any]:
        """File a moderation flag against a skill (PUBLIC report button).

        Body: ``{"reason": "<optional free text>"}``. Reports a skill by slug —
        the client resolves the slug to the skill id; for now the route passes the
        slug through as the target id so the queue carries an actionable handle.
        """
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — tolerate an empty/invalid body
            body = {}
        return await request.app.state.catalog_client.report(
            "skill", slug, reason=(body or {}).get("reason")
        )

    @app.post("/catalog/{slug}/status")
    async def catalog_set_skill_status(slug: str, request: Request):
        """Transition a skill's moderation status (MODERATOR-ONLY).

        Body: ``{"status": "approved"|"flagged"|"removed"|"pending"}``.
        """
        denied = _require_moderator(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        return await request.app.state.catalog_client.set_skill_status(
            slug, (body or {}).get("status", "")
        )

    @app.post("/catalog/comments/{comment_id}/status")
    async def catalog_set_comment_status(comment_id: str, request: Request):
        """Transition a comment's moderation status (MODERATOR-ONLY)."""
        denied = _require_moderator(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        return await request.app.state.catalog_client.set_comment_status(
            comment_id, (body or {}).get("status", "")
        )

    @app.get("/catalog/moderation/pending")
    async def catalog_list_pending(request: Request):
        """List skills awaiting manual review (MODERATOR-ONLY)."""
        denied = _require_moderator(request)
        if denied is not None:
            return denied
        rows = await request.app.state.catalog_client.list_pending()
        return {"pending": rows}

    @app.get("/catalog/moderation/flags")
    async def catalog_list_flags(request: Request):
        """List the moderation report queue (MODERATOR-ONLY)."""
        denied = _require_moderator(request)
        if denied is not None:
            return denied
        rows = await request.app.state.catalog_client.list_flags()
        return {"flags": rows}

    # --- Agent Skills (SKILL.md spec) endpoints ---

    @app.get("/skills/catalog/sources")
    async def skills_catalog_sources() -> dict[str, Any]:
        """List configured remote skill sources (for UI tabs)."""
        catalog = _get_skills_catalog(app)
        return {
            "sources": [
                {
                    "id": s.id, "label": s.label, "trust": s.trust,
                    "owner": s.owner, "repo": s.repo, "ref": s.ref,
                    "url": s.display_url,
                }
                for s in catalog.sources
            ]
        }

    @app.get("/skills/catalog")
    async def skills_catalog_list(
        source: str = "", q: str = "",
    ) -> dict[str, Any]:
        """List remote skills, optionally filtered by source_id and/or search query."""
        catalog = _get_skills_catalog(app)
        if source:
            entries = catalog.list_by_source(source)
            if q:
                qlow = q.lower()
                entries = [
                    e for e in entries
                    if qlow in e.name.lower() or qlow in e.description.lower()
                ]
        elif q:
            entries = catalog.search(q)
        else:
            entries = catalog.list_all()
        return {
            "results": [e.to_dict() for e in entries],
            "count": len(entries),
        }

    @app.post("/skills/catalog/refresh")
    async def skills_catalog_refresh(request: Request) -> dict[str, Any]:
        """Force-refresh the remote catalog index (fetches from GitHub)."""
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        force = bool(body.get("force", True))
        catalog = _get_skills_catalog(app)
        total = catalog.refresh_all(force=force)
        return {"status": "ok", "total_entries": total}

    @app.post("/skills/install")
    async def skills_install(request: Request) -> dict[str, Any]:
        """Install a skill from the remote catalog.

        Body: {"source_id": "anthropic", "name": "pdf-processing"}
        """
        from kernel.skills.installer import install_from_catalog
        body = await request.json()
        source_id = body.get("source_id", "")
        name = body.get("name", "")
        if not source_id or not name:
            return {"status": "error", "message": "source_id and name are required"}

        catalog = _get_skills_catalog(app)
        entry = catalog.get(source_id, name)
        if entry is None:
            return {
                "status": "error",
                "message": f"Skill '{name}' not found in source '{source_id}'",
            }

        try:
            result = install_from_catalog(
                entry,
                allow_overwrite=bool(body.get("overwrite", False)),
            )
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

        if result.ok:
            _get_skills_registry(app).reload()
            # Wire the installed skill into the live runtime, not just the catalog:
            # register it in the plugin registry (so it shows in /agents) and, if
            # template-backed (skill.yaml), load it into the executor so it can
            # actually run. Previously ONLY the catalog reloaded, so an installed
            # skill was a ghost — visible in "Мои навыки" but unrunnable (2d).
            # register_dir records the real install dir in PluginRegistry._dirs,
            # which _is_callable now consults — so a skill under %APPDATA%/KALI/
            # skills IS offered to the LLM palette, not just agents_dir (Phase A
            # Chunk 1 closed the prior install->LLM-callable gap).
            if result.install_path is not None:
                try:
                    app.state.plugin_registry.register_dir(result.install_path)
                    if (result.install_path / "skill.yaml").exists():
                        app.state.skill_executor.load_skill(result.install_path)
                except Exception:
                    logger.exception(
                        "Live registration of installed skill '%s' failed", result.skill_name
                    )
            return {
                "status": "ok",
                "skill_name": result.skill_name,
                "install_path": str(result.install_path),
                "warnings": result.warnings,
            }
        return {"status": "error", "message": result.error, "skill_name": result.skill_name}

    @app.post("/skills/uninstall")
    async def skills_uninstall(request: Request) -> dict[str, Any]:
        """Remove a user-installed skill."""
        from kernel.skills.installer import uninstall
        body = await request.json()
        name = body.get("name", "")
        if not name:
            return {"status": "error", "message": "name is required"}
        ok = uninstall(name)
        if ok:
            _get_skills_registry(app).reload()
        return {"status": "ok" if ok else "error", "removed": ok}

    @app.post("/skills/install-bundle")
    async def skills_install_bundle(request: Request) -> dict[str, Any]:
        """Install a skill from a posted base64url(.tar.gz) bundle — the P2P
        share-loop import path.

        Body: {"data": "<base64url>", "name"?: "...", "overwrite"?: false}.
        Held to the same validation + AST safety gate as a catalog install.
        """
        from kernel.skills.installer import install_from_bundle

        body = await request.json()
        data = body.get("data", "")
        if not data:
            return {"status": "error", "message": "data is required"}

        try:
            result = install_from_bundle(
                data,
                expected_name=body.get("name") or None,
                allow_overwrite=bool(body.get("overwrite", False)),
            )
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

        if result.ok:
            _get_skills_registry(app).reload()
            # Wire the installed skill into the live runtime, not just the catalog:
            # register it in the plugin registry (so it shows in /agents) and, if
            # template-backed (skill.yaml), load it into the executor so it can
            # actually run. Previously ONLY the catalog reloaded, so an installed
            # skill was a ghost — visible in "Мои навыки" but unrunnable (2d).
            # register_dir records the real install dir in PluginRegistry._dirs,
            # which _is_callable now consults — so a skill under %APPDATA%/KALI/
            # skills IS offered to the LLM palette, not just agents_dir (Phase A
            # Chunk 1 closed the prior install->LLM-callable gap).
            if result.install_path is not None:
                try:
                    app.state.plugin_registry.register_dir(result.install_path)
                    if (result.install_path / "skill.yaml").exists():
                        app.state.skill_executor.load_skill(result.install_path)
                except Exception:
                    logger.exception(
                        "Live registration of installed skill '%s' failed", result.skill_name
                    )
            return {
                "status": "ok",
                "skill_name": result.skill_name,
                "install_path": str(result.install_path),
                "warnings": result.warnings,
            }
        return {"status": "error", "message": result.error, "skill_name": result.skill_name}

    @app.get("/skills/{name}/export")
    async def skills_export(name: str) -> dict[str, Any]:
        """Export an installed skill as a portable base64url(.tar.gz) bundle for
        P2P sharing (the UGC share loop). Self-contained — a friend imports it
        via POST /skills/install-bundle with no catalog or server involved.
        """
        import base64
        import tempfile
        from pathlib import Path

        from kernel.skills.publisher import package_skill
        from kernel.skills.validator import validate_frontmatter

        reg = _get_skills_registry(app)
        skill = reg.get(name)
        if skill is not None:
            skill_dir = skill.skill_dir
        else:
            # Voice-built agents live under agents_dir (manifest.yaml + skill.yaml,
            # no SKILL.md) and aren't indexed by SkillsRegistry; the live plugin
            # registry tracks every agent's real directory (Phase A share fix).
            skill_dir = app.state.plugin_registry.skill_dir_for(name)
        if skill_dir is None:
            return {"status": "error", "message": f"Skill '{name}' not found locally"}

        # Honest-fail: a non-spec name (uppercase / underscore / non-ascii — the
        # voice builder's slugify uses \w without re.ASCII, so Cyrillic survives)
        # would synthesize a SKILL.md the receiver's strict loader rejects on
        # import. Refuse here rather than ship a bundle that dies on the friend.
        if not validate_frontmatter({"name": name, "description": "x"}, expected_name=name).valid:
            return {
                "status": "error",
                "message": (
                    f"Agent name '{name}' can't be shared yet — names must be "
                    "lowercase latin letters, digits and single hyphens."
                ),
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                bundle = package_skill(skill_dir, output_dir=Path(tmp))
                raw = bundle.read_bytes()
        except Exception as exc:
            return {"status": "error", "message": f"Export failed: {exc}"}

        data = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return {"status": "ok", "name": name, "data": data, "size": len(raw)}

    @app.get("/skills/{name}/reel")
    async def skills_reel(name: str):
        """Render a 9:16 voice reel (MP4) for a created agent — the UGC share
        hook. Honest-fail JSON envelope on any error (mobile falls back to the
        PNG card). Mirrors /skills/{name}/export resolution + name gate."""
        import shutil
        import tempfile
        from pathlib import Path

        from fastapi.responses import FileResponse, JSONResponse
        from starlette.background import BackgroundTask

        from kernel.llm_router import LLMRouter
        from kernel.reel import generate_reel
        from kernel.share_links import build_import_link
        from kernel.skills.validator import validate_frontmatter

        reg = _get_skills_registry(app)
        skill = reg.get(name)
        if skill is not None:
            description = skill.description
        else:
            manifest = app.state.plugin_registry.get(name)
            if manifest is None:
                return JSONResponse(
                    {"status": "error", "name": name, "message": f"Agent '{name}' not found locally"}
                )
            description = manifest.description
        if not validate_frontmatter(
            {"name": name, "description": "x"}, expected_name=name
        ).valid:
            return JSONResponse({
                "status": "error",
                "name": name,
                "message": (
                    f"Agent name '{name}' can't be shared yet — names must be "
                    "lowercase latin letters, digits and single hyphens."
                ),
            })
        tmp = None
        try:
            export = await skills_export(name)
            if export.get("status") != "ok":
                return JSONResponse(export)
            link = build_import_link(name=name, bundle=export["data"])
            router = LLMRouter(app.state.config_manager.config.llm)
            tmp = Path(tempfile.mkdtemp(prefix="kali_reel_"))
            out = await generate_reel(
                name=name, description=description, link=link,
                router=router, out_dir=tmp,
            )
            return FileResponse(
                str(out), media_type="video/mp4", filename=f"{name}.mp4",
                background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
            )
        except Exception as exc:  # noqa: BLE001 — honest error, never 500 to user
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
            logger.exception("reel render failed for %s", name)
            return JSONResponse(
                {"status": "error", "name": name, "message": f"Reel render failed: {exc}"}
            )

    @app.get("/skills/installed")
    async def skills_installed() -> dict[str, Any]:
        """List all skills discovered locally (builtin + user)."""
        reg = _get_skills_registry(app)
        return {
            "results": [m.to_dict() for m in reg.list_all()],
            "count": len(reg.list_all()),
        }

    @app.post("/skills/validate")
    async def skills_validate(request: Request) -> dict[str, Any]:
        """Validate a local skill against the Agent Skills spec.

        Body: {"name": "my-skill"}  — name of an installed skill.
        """
        from kernel.skills.publisher import validate_skill

        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return {"status": "error", "message": "name is required"}

        reg = _get_skills_registry(app)
        skill = reg.get(name)
        if skill is None:
            return {"status": "error", "message": f"Skill '{name}' not found locally"}

        manifest, errors, warnings = validate_skill(skill.skill_dir)
        return {
            "status": "ok" if not errors else "invalid",
            "skill_name": name,
            "valid": manifest is not None and not errors,
            "errors": errors,
            "warnings": warnings,
        }

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

    @app.post("/skills/publish")
    async def skills_publish(request: Request) -> dict[str, Any]:
        """Prepare a skill bundle for community catalog submission.

        Body: {"name": "my-skill"}

        Returns bundle path + next-step instructions (does not push to GitHub).
        """
        from kernel.skills.publisher import publish_skill

        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return {"status": "error", "message": "name is required"}

        reg = _get_skills_registry(app)
        skill = reg.get(name)
        if skill is None:
            return {"status": "error", "message": f"Skill '{name}' not found locally"}

        # skip_safety is NOT exposed over HTTP — the AST safety gate must always
        # run on a publish path (it is an internal/testing-only kwarg).
        result = publish_skill(
            skill.skill_dir,
            skip_safety=False,
            include_scripts=bool(body.get("include_scripts", True)),
        )

        response: dict[str, Any] = {
            "status": "ok" if result.ok else "error",
            "skill_name": result.skill_name,
            "ok": result.ok,
            "errors": result.errors,
            "warnings": result.warnings,
            "safety_issues": result.safety_issues,
            "catalog_repo_url": result.catalog_repo_url,
            "instructions": result.instructions,
        }
        if result.bundle_path:
            response["bundle_path"] = str(result.bundle_path)
            response["bundle_name"] = result.bundle_path.name
        return response

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
    from kernel.routers import chat as chat_router
    from kernel.routers import voice as voice_router

    app.include_router(chat_router.router)
    app.include_router(voice_router.router)

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
