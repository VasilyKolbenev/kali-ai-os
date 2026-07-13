"""FastAPI application — entry point for the KALI kernel."""

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
from fastapi import FastAPI, WebSocket
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

    # Domain routers (2026-07-13 split) — imported here, not at module top,
    # so routers may import kernel.routers._shared without an import cycle.
    # Registration order is inter-module-safe: extracted paths are exact
    # (no parametrized shadowing against the remaining inline routes).
    from kernel.routers import agents as agents_router
    from kernel.routers import builder as builder_router
    from kernel.routers import catalog as catalog_router
    from kernel.routers import chat as chat_router
    from kernel.routers import life as life_router
    from kernel.routers import skills as skills_router
    from kernel.routers import system as system_router
    from kernel.routers import voice as voice_router
    from kernel.routers import ws as ws_router

    app.include_router(chat_router.router)
    app.include_router(voice_router.router)
    app.include_router(skills_router.router)
    app.include_router(catalog_router.router)
    app.include_router(agents_router.router)
    app.include_router(builder_router.router)
    app.include_router(life_router.router)
    app.include_router(system_router.router)
    app.include_router(ws_router.router)

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
