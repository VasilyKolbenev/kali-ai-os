"""Integration tests for FastAPI server and WebSocket."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from kernel.main import create_app
from kernel.models import Event


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

    async def test_health_echoes_desktop_instance_id(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """Ownership-контракт A3: /health возвращает KALI_DESKTOP_INSTANCE_ID."""
        monkeypatch.setenv("KALI_DESKTOP_INSTANCE_ID", "abc-123")
        resp = await client.get("/health")
        assert resp.json()["desktop_instance_id"] == "abc-123"

    async def test_health_instance_id_null_when_launched_manually(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """Ручной запуск без env → desktop_instance_id == null (не наш backend)."""
        monkeypatch.delenv("KALI_DESKTOP_INSTANCE_ID", raising=False)
        resp = await client.get("/health")
        assert resp.json()["desktop_instance_id"] is None


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
        names = {t["function"]["name"] for t in data}
        assert any("test-agent__greet" in n for n in names)
        # The built-in list-my-agents tool is part of the palette (core-loop 2b).
        assert "kali__list_my_agents" in names


class TestConsentRoutes:
    """M2.2: persisted, revocable consent surfaced to the UI."""

    async def test_consents_empty_initially(self, client: AsyncClient) -> None:
        resp = await client.get("/agents/consents")
        assert resp.status_code == 200
        assert resp.json() == {}

    async def test_revoke_persists_and_is_listed(self, app, client: AsyncClient) -> None:
        resp = await client.post("/agents/test-agent/revoke")
        assert resp.status_code == 200
        assert resp.json() == {"status": "revoked", "agent": "test-agent"}

        # GET /agents/consents reflects it so the UI can show durable state
        consents = (await client.get("/agents/consents")).json()
        assert consents == {"test-agent": "revoked"}

        # ...and it is persisted in the DB (survives a restart per M2.2)
        assert await app.state.database.get_consent("test-agent") == "revoked"


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


class TestLlmProviderSwitch:
    """WS-2 #2.5 — the Settings provider/model picker must actually switch the
    LLM router. The router reads its provider/model from ``config.llm`` (the
    ConfigManager source of truth), NOT from ``os.environ``. So the picker has
    to write through ``PATCH /config`` — exactly like ``VoiceSettings`` —
    otherwise it shows "saved" while the router keeps the old brain.

    The chat path constructs ``LLMRouter(app.state.config_manager.config.llm)``
    fresh per request, so a config write takes effect on the next message.
    """

    async def test_post_settings_does_not_switch_router_provider(
        self, app, client: AsyncClient
    ) -> None:
        """Regression pin: the OLD path (``POST /settings``) writes env only and
        does NOT change the router's source of truth — this is the bug."""
        cm = app.state.config_manager
        before = cm.config.llm.cloud_provider

        resp = await client.post(
            "/settings",
            json={"provider": "deepseek", "deepseek_model": "deepseek-chat"},
        )
        assert resp.status_code == 200

        # The router reads config.llm, which POST /settings never touched.
        assert cm.config.llm.cloud_provider == before
        assert cm.config.llm.cloud_provider != "deepseek"

    async def test_config_patch_switches_router_source_of_truth(
        self, app, client: AsyncClient
    ) -> None:
        """The FIX: routing provider+model through ``PATCH /config`` changes the
        value a freshly-built router (the ``/chat`` path) will use."""
        from kernel.llm_router import LLMRouter

        cm = app.state.config_manager

        resp = await client.patch(
            "/config",
            json={"llm": {"cloud_provider": "openai", "cloud_model": "gpt-4.1"}},
        )
        assert resp.status_code == 200, resp.text

        # Source of truth changed...
        assert cm.config.llm.cloud_provider == "openai"
        assert cm.config.llm.cloud_model == "gpt-4.1"

        # ...so the router the chat handler builds now targets the new provider.
        router = LLMRouter(cm.config.llm)
        assert router.config.cloud_provider == "openai"
        assert router.config.cloud_model == "gpt-4.1"

    async def test_config_patch_llm_leaves_other_sections_intact(
        self, client: AsyncClient
    ) -> None:
        """An ``llm`` patch is surgical — it must not disturb voice/server."""
        before = (await client.get("/config")).json()

        resp = await client.patch(
            "/config",
            json={"llm": {"cloud_provider": "google", "cloud_model": "gemini-2.5-flash"}},
        )
        assert resp.status_code == 200

        after = (await client.get("/config")).json()
        assert after["llm"]["cloud_provider"] == "google"
        assert after["voice"] == before["voice"]
        assert after["server"] == before["server"]
        # local-side LLM fields are preserved by the merge patch
        assert after["llm"]["local_provider"] == before["llm"]["local_provider"]


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


class TestScheduledSkillTrigger:
    """A fired cron (skill.{name}.trigger) must actually run the skill and
    deliver its result — previously the event had no subscriber (core-loop 3b)."""

    async def test_trigger_runs_skill_and_notifies(self, app) -> None:
        s = app.state
        s.skill_executor.get_skill_info = MagicMock(
            return_value={"name": "r", "template": "reminder", "display_name": "Пей воду", "config": {}}
        )
        s.skill_executor.execute = AsyncMock(
            return_value={"should_fire": True, "message": "Пора пить воду!"}
        )
        before = len(s.notifications.get_pending())

        await s.event_bus.publish(Event(topic="skill.r.trigger", source="scheduler", payload={}))

        s.skill_executor.execute.assert_awaited_once_with("r", "check")
        pending = s.notifications.get_pending()
        assert len(pending) == before + 1
        assert "Пора пить воду" in pending[-1].message

    async def test_trigger_skips_notification_when_not_firing(self, app) -> None:
        s = app.state
        s.skill_executor.get_skill_info = MagicMock(
            return_value={"name": "r", "template": "reminder", "display_name": "r", "config": {}}
        )
        s.skill_executor.execute = AsyncMock(return_value={"should_fire": False, "reason": "too_soon"})
        before = len(s.notifications.get_pending())

        await s.event_bus.publish(Event(topic="skill.r.trigger", source="scheduler", payload={}))

        s.skill_executor.execute.assert_awaited_once()
        assert len(s.notifications.get_pending()) == before


class TestInstallBundleRegistersLive:
    """An imported bundle must be wired into the live runtime (plugin registry +
    executor), not just the catalog — otherwise it's a ghost (core-loop 2d)."""

    async def test_imported_skill_is_registered_and_loaded(
        self, app, client: AsyncClient, tmp_path: Path
    ) -> None:
        s = app.state
        s.skills_registry = MagicMock()  # avoid a real catalog rescan in the route

        skill_dir = tmp_path / "shared-skill"
        skill_dir.mkdir()
        (skill_dir / "manifest.yaml").write_text(
            yaml.dump(
                {
                    "name": "shared-skill",
                    "version": "1.0.0",
                    "description": "Shared",
                    "protocol": "skill",
                    "tools": [{"name": "run", "description": "r", "parameters": {}}],
                    "capabilities": ["shared-skill.run"],
                    "permissions": [],
                }
            )
        )
        (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))

        from kernel.skills.installer import InstallResult

        fake = InstallResult(ok=True, skill_name="shared-skill", install_path=skill_dir)
        with patch("kernel.skills.installer.install_from_bundle", return_value=fake):
            resp = await client.post("/skills/install-bundle", json={"data": "x"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # Live now: present in the plugin registry AND the executor — not the
        # catalog alone, which was the whole bug.
        assert s.plugin_registry.get("shared-skill") is not None
        assert "shared-skill" in s.skill_executor.list_skills()


@pytest.mark.core_loop
class TestExportVoiceAgent:
    """A voice-built agent (manifest.yaml + skill.yaml, no SKILL.md) under
    agents_dir is exportable via the plugin-registry fallback (Phase A)."""

    async def test_export_voice_agent_returns_bundle(
        self, app, client: AsyncClient, tmp_path: Path
    ) -> None:
        import base64

        skill_dir = app.state.plugin_registry.agents_dir / "water-tracker"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "manifest.yaml").write_text(
            yaml.dump({"name": "water-tracker", "version": "1.0.0",
                       "description": "Track water intake daily", "protocol": "skill",
                       "tools": [{"name": "log", "description": "Log", "parameters": {}}],
                       "capabilities": ["water-tracker.log"], "permissions": []})
        )
        (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))
        app.state.plugin_registry.register_dir(skill_dir)

        resp = await client.get("/skills/water-tracker/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok", body
        assert isinstance(body["data"], str) and body["data"]
        raw = base64.urlsafe_b64decode(body["data"] + "=" * (-len(body["data"]) % 4))
        assert raw[:2] == b"\x1f\x8b"  # gzip magic

    async def test_export_route_bundle_installs_and_is_callable(
        self, app, client: AsyncClient, tmp_path: Path
    ) -> None:
        """End-to-end share loop at ROUTE level: the EXPORT route's bundle must
        actually install on a friend's device AND be LLM-callable + runnable —
        not just be valid gzip. Register a voice skill (manifest.yaml + skill.yaml,
        no SKILL.md) → GET /skills/{name}/export → feed the returned base64 to
        install_from_bundle(target_dir=<tmp>) → register the installed dir into a
        FRESH PluginRegistry → assert the tool is offered AND a real SkillExecutor
        runs it. Install targets tmp (NOT real %APPDATA%/KALI/skills)."""
        import base64

        from kernel.plugin_registry import PluginRegistry
        from kernel.skill_executor import SkillExecutor
        from kernel.skills.installer import install_from_bundle

        # Creator side: a voice-built tracker agent registered live.
        skill_dir = app.state.plugin_registry.agents_dir / "sleep-tracker"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "manifest.yaml").write_text(
            yaml.dump({"name": "sleep-tracker", "version": "1.0.0",
                       "description": "Track hours of sleep each night daily",
                       "protocol": "skill",
                       "tools": [{"name": "log", "description": "Log a data point",
                                  "parameters": {}}],
                       "capabilities": ["sleep-tracker.log"], "permissions": []})
        )
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"template": "tracker", "config": {}})
        )
        app.state.plugin_registry.register_dir(skill_dir)

        # Export via the REAL route.
        resp = await client.get("/skills/sleep-tracker/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok", body

        # Friend side: install the route's bundle into a TMP dir (never appdata).
        install_root = tmp_path / "friend_skills"
        result = install_from_bundle(body["data"], target_dir=install_root)
        assert result.ok, result.error
        installed = install_root / "sleep-tracker"
        assert (installed / "SKILL.md").is_file()    # synthesized by packager
        assert (installed / "skill.yaml").is_file()   # config carried for execution

        # Imported skill is LLM-callable from a FRESH registry rooted elsewhere.
        fresh_agents = tmp_path / "friend_agents"
        fresh_agents.mkdir()
        reg = PluginRegistry(fresh_agents)
        reg.register_dir(installed)
        tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
        assert "sleep-tracker__log" in tool_names

        # ...and actually RUNS through the real template executor (no LLM needed).
        executor = SkillExecutor(data_dir=tmp_path / "friend_data")
        executor.load_skill(installed)
        assert "sleep-tracker" in executor.list_skills()
        run = await executor.execute("sleep-tracker", "log", {"amount": 7})
        assert isinstance(run, dict)
        assert "error" not in run, run        # tracker.log never errors on happy path
        assert run["total"] == 7.0            # value actually recorded

    async def test_export_non_spec_name_fails_honestly(
        self, app, client: AsyncClient, tmp_path: Path
    ) -> None:
        """A Cyrillic / non-spec agent name must export as status:"error" with a
        message about the name — NOT a status:ok bundle that dies on the friend's
        strict loader. The voice builder's slugify keeps Cyrillic, so 'трекер'
        can be registered locally yet is unshareable per the Agent-Skills name
        spec; the export route refuses it up front."""
        bad_name = "трекер"
        skill_dir = app.state.plugin_registry.agents_dir / bad_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "manifest.yaml").write_text(
            yaml.dump({"name": bad_name, "version": "1.0.0",
                       "description": "Трекер воды на русском языке каждый день",
                       "protocol": "skill",
                       "tools": [{"name": "log", "description": "Log", "parameters": {}}],
                       "capabilities": [f"{bad_name}.log"], "permissions": []})
        )
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"template": "tracker", "config": {}})
        )
        app.state.plugin_registry.register_dir(skill_dir)

        resp = await client.get(f"/skills/{bad_name}/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error", body
        assert "name" in body["message"].lower()
        assert "data" not in body  # no bundle shipped


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


class TestSpeakTaskLifetime:
    """The auto-speak task must be retained in a set so the GC can't cancel it."""

    async def test_speak_tasks_set_initialized(self, app) -> None:
        assert isinstance(app.state._speak_tasks, set)

    async def test_chat_tracks_then_discards_speak_task(
        self, app, client: AsyncClient
    ) -> None:
        import threading

        import kernel.voice.jarvis_sounds as js
        from kernel.llm_router import LLMResponse, LLMRouter

        release = threading.Event()

        def _block_play(_clip) -> None:  # type: ignore[no-untyped-def]
            release.wait(timeout=5.0)

        canned = LLMResponse(
            text="Hi there friend", tool_calls=None, provider_used="mock", latency_ms=0
        )

        with patch.object(LLMRouter, "route", AsyncMock(return_value=canned)), \
                patch.object(js, "should_use_clip", return_value="clip.wav"), \
                patch.object(js, "play_reaction", side_effect=_block_play):
            await client.post("/chat", json={"text": "hello there friend"})
            # The speak task is created synchronously before /chat returns and
            # is blocked inside play_reaction → it must be tracked.
            assert len(app.state._speak_tasks) >= 1
            release.set()

        # Drain: _speak_response has a trailing 0.5s anti-echo sleep, so give
        # it room; the done-callback then discards the task from the set.
        for _ in range(400):
            if not app.state._speak_tasks:
                break
            await asyncio.sleep(0.02)
        assert len(app.state._speak_tasks) == 0


class TestModelDownloadTaskLifetime:
    """The first-run download task must be retained + report failures honestly.

    Fire-and-forget create_task could be GC-cancelled, stalling the download so
    download_complete never fires and the onboarding UI hangs forever.
    """

    async def test_download_retains_live_task(self, app, client: AsyncClient) -> None:
        import threading

        import kernel.model_downloader as md

        release = threading.Event()

        def _block(name, url, cb):  # type: ignore[no-untyped-def]
            release.wait(timeout=5.0)
            return True

        with patch.object(md, "get_missing_models", return_value=[
            {"name": "m", "url": "http://x", "description": "d"}
        ]), patch.object(md, "download_model", side_effect=_block):
            resp = await client.post("/models/download")
            assert resp.json()["status"] == "started"
            task = app.state._model_download_task
            assert isinstance(task, asyncio.Task)
            assert not task.done()
            release.set()
            task.cancel()

    async def test_download_failure_publishes_failed_event(
        self, app, client: AsyncClient
    ) -> None:
        import kernel.model_downloader as md

        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        app.state.event_bus.subscribe("system.models.download_failed", handler)

        def _boom(name, url, cb):  # type: ignore[no-untyped-def]
            raise OSError("disk full")

        with patch.object(md, "get_missing_models", return_value=[
            {"name": "m", "url": "http://x", "description": "d"}
        ]), patch.object(md, "download_model", side_effect=_boom):
            await client.post("/models/download")
            task = app.state._model_download_task
            with pytest.raises(OSError):
                await task

        # done-callback fires after the task finishes and schedules the publish
        # on the loop; poll a few ticks for it to run.
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
        assert any(e.topic == "system.models.download_failed" for e in received)

    async def test_soft_failure_publishes_failed_not_complete(
        self, app, client: AsyncClient
    ) -> None:
        """download_model returning False (no raise) must be reported as a
        failure, never a falsely-emitted download_complete (success)."""
        import kernel.model_downloader as md

        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        app.state.event_bus.subscribe("system.models.download_failed", handler)
        app.state.event_bus.subscribe("system.models.download_complete", handler)

        def _soft_fail(name, url, cb):  # type: ignore[no-untyped-def]
            return False

        with patch.object(md, "get_missing_models", return_value=[
            {"name": "m", "url": "http://x", "description": "d"}
        ]), patch.object(md, "download_model", side_effect=_soft_fail):
            await client.post("/models/download")
            task = app.state._model_download_task
            await task

        # The publish runs on the loop; poll a few ticks for it to land.
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
        topics = {e.topic for e in received}
        assert "system.models.download_failed" in topics
        assert "system.models.download_complete" not in topics


class _StubSocialCatalog:
    """A stand-in catalog_client recording social calls + returning canned results.

    Lets the route tests assert the slug/body wiring AND that the route passes the
    CatalogClient result through VERBATIM (notably an honest "sign-in required",
    never a fake success).
    """

    def __init__(self, results: dict[str, object] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append((name, args, kwargs))
        return self.results.get(name, {"status": "ok"})

    async def like(self, slug: str):  # type: ignore[no-untyped-def]
        return self._record("like", slug)

    async def unlike(self, slug: str):  # type: ignore[no-untyped-def]
        return self._record("unlike", slug)

    async def set_rating(self, slug: str, stars: int):  # type: ignore[no-untyped-def]
        return self._record("set_rating", slug, stars)

    async def post_comment(self, slug: str, body: str):  # type: ignore[no-untyped-def]
        return self._record("post_comment", slug, body)

    async def list_comments(self, slug: str):  # type: ignore[no-untyped-def]
        return self._record("list_comments", slug)

    async def get_social(self, slug: str):  # type: ignore[no-untyped-def]
        return self._record("get_social", slug)

    # --- moderation lifecycle (WS-3 Task 3.7) ---
    async def report(self, target_type, target_id, reason=None):  # type: ignore[no-untyped-def]
        return self._record("report", target_type, target_id, reason=reason)

    async def set_skill_status(self, slug, status):  # type: ignore[no-untyped-def]
        return self._record("set_skill_status", slug, status)

    async def set_comment_status(self, comment_id, status):  # type: ignore[no-untyped-def]
        return self._record("set_comment_status", comment_id, status)

    async def list_pending(self):  # type: ignore[no-untyped-def]
        return self._record("list_pending")

    async def list_flags(self):  # type: ignore[no-untyped-def]
        return self._record("list_flags")


class TestCatalogSocialRoutes:
    """WS-3 Task 3.4 — social routes pass the CatalogClient result through verbatim."""

    async def test_like_route_calls_client_and_returns_result(
        self, app, client: AsyncClient
    ) -> None:
        stub = _StubSocialCatalog({"like": {"status": "ok", "liked": True}})
        app.state.catalog_client = stub

        resp = await client.post("/catalog/weather-bot/like")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "liked": True}
        assert stub.calls[0] == ("like", ("weather-bot",), {})

    async def test_unlike_route(self, app, client: AsyncClient) -> None:
        stub = _StubSocialCatalog({"unlike": {"status": "ok", "liked": False}})
        app.state.catalog_client = stub

        resp = await client.request("DELETE", "/catalog/weather-bot/like")

        assert resp.status_code == 200
        assert resp.json()["liked"] is False
        assert stub.calls[0][0] == "unlike"

    async def test_rating_route_passes_stars_from_body(
        self, app, client: AsyncClient
    ) -> None:
        stub = _StubSocialCatalog({"set_rating": {"status": "ok", "stars": 4}})
        app.state.catalog_client = stub

        resp = await client.post("/catalog/weather-bot/rating", json={"stars": 4})

        assert resp.status_code == 200
        assert resp.json()["stars"] == 4
        assert stub.calls[0] == ("set_rating", ("weather-bot", 4), {})

    async def test_rating_route_signed_out_passthrough(
        self, app, client: AsyncClient
    ) -> None:
        # The honest "sign-in required" must reach the UI as such — NOT a 200 "ok".
        stub = _StubSocialCatalog({"set_rating": {"status": "sign-in required"}})
        app.state.catalog_client = stub

        resp = await client.post("/catalog/weather-bot/rating", json={"stars": 5})

        assert resp.status_code == 200
        assert resp.json() == {"status": "sign-in required"}

    async def test_comment_route_passes_body(
        self, app, client: AsyncClient
    ) -> None:
        stub = _StubSocialCatalog({"post_comment": {"status": "pending"}})
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/weather-bot/comment", json={"body": "nice"}
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
        assert stub.calls[0] == ("post_comment", ("weather-bot", "nice"), {})

    async def test_comment_route_signed_out_passthrough(
        self, app, client: AsyncClient
    ) -> None:
        stub = _StubSocialCatalog({"post_comment": {"status": "sign-in required"}})
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/weather-bot/comment", json={"body": "nice"}
        )

        assert resp.json() == {"status": "sign-in required"}

    async def test_list_comments_route(self, app, client: AsyncClient) -> None:
        stub = _StubSocialCatalog(
            {"list_comments": [{"body": "great", "status": "approved"}]}
        )
        app.state.catalog_client = stub

        resp = await client.get("/catalog/weather-bot/comments")

        assert resp.status_code == 200
        body = resp.json()
        assert body["comments"][0]["body"] == "great"
        assert stub.calls[0] == ("list_comments", ("weather-bot",), {})

    async def test_social_route_returns_aggregate(
        self, app, client: AsyncClient
    ) -> None:
        stub = _StubSocialCatalog(
            {
                "get_social": {
                    "like_count": 3,
                    "rating_count": 2,
                    "avg_rating": 3.0,
                    "liked": True,
                    "rated": 4,
                }
            }
        )
        app.state.catalog_client = stub

        resp = await client.get("/catalog/weather-bot/social")

        assert resp.status_code == 200
        body = resp.json()
        assert body["like_count"] == 3
        assert body["avg_rating"] == 3.0
        assert stub.calls[0] == ("get_social", ("weather-bot",), {})


class TestCatalogModerationRoutes:
    """WS-3 Task 3.7 — report is PUBLIC; transitions/queue are MODERATOR-ONLY (403)."""

    async def test_report_route_is_public(self, app, client: AsyncClient) -> None:
        # No moderator token needed — the report button is open to everyone.
        stub = _StubSocialCatalog({"report": {"status": "ok"}})
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/weather-bot/report", json={"reason": "spam"}
        )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert stub.calls[0] == (
            "report",
            ("skill", "weather-bot"),
            {"reason": "spam"},
        )

    async def test_set_skill_status_forbidden_without_token(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_MODERATOR_TOKEN", raising=False)
        stub = _StubSocialCatalog({"set_skill_status": {"status": "ok"}})
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/weather-bot/status", json={"status": "approved"}
        )

        assert resp.status_code == 403
        # The privileged transition must NOT have been called.
        assert stub.calls == []

    async def test_set_skill_status_allowed_with_token(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALI_MODERATOR_TOKEN", "secret-mod")
        stub = _StubSocialCatalog(
            {"set_skill_status": {"status": "ok", "skill_status": "approved"}}
        )
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/weather-bot/status",
            json={"status": "approved"},
            headers={"X-Moderator-Token": "secret-mod"},
        )

        assert resp.status_code == 200
        assert resp.json()["skill_status"] == "approved"
        assert stub.calls[0] == ("set_skill_status", ("weather-bot", "approved"), {})

    async def test_set_skill_status_wrong_token_forbidden(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALI_MODERATOR_TOKEN", "secret-mod")
        stub = _StubSocialCatalog({"set_skill_status": {"status": "ok"}})
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/weather-bot/status",
            json={"status": "approved"},
            headers={"X-Moderator-Token": "WRONG"},
        )

        assert resp.status_code == 403
        assert stub.calls == []

    async def test_set_comment_status_requires_token(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_MODERATOR_TOKEN", raising=False)
        stub = _StubSocialCatalog({"set_comment_status": {"status": "ok"}})
        app.state.catalog_client = stub

        resp = await client.post(
            "/catalog/comments/c1/status", json={"status": "removed"}
        )

        assert resp.status_code == 403
        assert stub.calls == []

    async def test_list_pending_forbidden_without_token(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_MODERATOR_TOKEN", raising=False)
        stub = _StubSocialCatalog({"list_pending": [{"slug": "a"}]})
        app.state.catalog_client = stub

        resp = await client.get("/catalog/moderation/pending")

        assert resp.status_code == 403
        assert stub.calls == []

    async def test_list_pending_allowed_with_token(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALI_MODERATOR_TOKEN", "secret-mod")
        stub = _StubSocialCatalog({"list_pending": [{"slug": "a"}, {"slug": "b"}]})
        app.state.catalog_client = stub

        resp = await client.get(
            "/catalog/moderation/pending",
            headers={"X-Moderator-Token": "secret-mod"},
        )

        assert resp.status_code == 200
        assert resp.json()["pending"] == [{"slug": "a"}, {"slug": "b"}]
        assert stub.calls[0] == ("list_pending", (), {})

    async def test_list_flags_allowed_with_token(
        self, app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALI_MODERATOR_TOKEN", "secret-mod")
        stub = _StubSocialCatalog({"list_flags": [{"id": "f1"}]})
        app.state.catalog_client = stub

        resp = await client.get(
            "/catalog/moderation/flags",
            headers={"X-Moderator-Token": "secret-mod"},
        )

        assert resp.status_code == 200
        assert resp.json()["flags"] == [{"id": "f1"}]
        assert stub.calls[0] == ("list_flags", (), {})


class _StubMergeCatalog:
    """A catalog_client stand-in for the /catalog/community merge route.

    Returns canned Supabase UGC (``browse``/``search``), social aggregates, and
    local results so the route's merge + dedup + degradation can be asserted
    without a live Supabase or GitHub.
    """

    def __init__(
        self,
        *,
        ugc: list[dict] | None = None,
        local: list[dict] | None = None,
        social: dict[str, dict] | None = None,
    ) -> None:
        self._ugc = ugc or []
        self._local = local or []
        self._social = social or {}

    async def browse(self, category=None, limit=50):  # type: ignore[no-untyped-def]
        return list(self._ugc)

    async def search(self, query, category=None, limit=10):  # type: ignore[no-untyped-def]
        q = (query or "").lower()
        return [r for r in self._ugc if q in r.get("name", "").lower()]

    async def get_social(self, slug):  # type: ignore[no-untyped-def]
        return self._social.get(slug, {})

    async def local_search(self, query, agents_dir=None):  # type: ignore[no-untyped-def]
        return list(self._local)


class _StubGithubCatalog:
    """A SkillsCatalog stand-in: curated entries with NO network refresh."""

    def __init__(self, entries: list[dict] | None = None, *, raise_refresh=False) -> None:
        self._entries = entries or []
        self._raise_refresh = raise_refresh

    def refresh_source(self, source_id, force=False):  # type: ignore[no-untyped-def]
        if self._raise_refresh:
            raise RuntimeError("github offline")
        return []

    def list_by_source(self, source_id):  # type: ignore[no-untyped-def]
        return [_CuratedEntry(e) for e in self._entries]


class _CuratedEntry:
    """Minimal CatalogEntry-like object exposing name/description/to_dict()."""

    def __init__(self, d: dict) -> None:
        self._d = d
        self.name = d.get("name", "")
        self.description = d.get("description", "")

    def to_dict(self) -> dict:
        return dict(self._d)


class TestCatalogCommunityRoute:
    """WS-3 Task 3.5 — /catalog/community merges Supabase UGC ∪ GitHub curated."""

    async def test_merges_ugc_and_curated_deduped(
        self, app, client: AsyncClient
    ) -> None:
        app.state.catalog_client = _StubMergeCatalog(
            ugc=[
                {"slug": "weather-bot", "name": "Weather Bot", "description": "w"},
                {"slug": "shared", "name": "Shared", "description": "s"},
            ],
            social={"weather-bot": {"like_count": 5, "rating_count": 2, "avg_rating": 4.0}},
        )
        # A curated entry that duplicates "shared" by name must be deduped out.
        app.state.skills_catalog = _StubGithubCatalog(
            entries=[
                {"name": "pdf-skill", "description": "p", "source_id": "kali",
                 "trust": "official", "metadata": {}, "repo_owner": "anthropics"},
                {"name": "Shared", "description": "dup", "source_id": "kali",
                 "trust": "official", "metadata": {}, "repo_owner": "x"},
            ]
        )

        resp = await client.get("/catalog/community")

        assert resp.status_code == 200
        body = resp.json()
        cards = body["results"]
        names = [c["name"] for c in cards]
        # UGC first (both), then the curated remainder (pdf-skill only — "Shared"
        # deduped against the UGC slug "shared").
        assert names == ["Weather Bot", "Shared", "pdf-skill"]
        assert body["count"] == 3
        sources = {c["name"]: c["source"] for c in cards}
        assert sources["Weather Bot"] == "ugc"
        assert sources["pdf-skill"] == "curated"
        # Social counts enriched the UGC card.
        weather = next(c for c in cards if c["name"] == "Weather Bot")
        assert weather["like_count"] == 5
        assert weather["avg_rating"] == 4.0

    async def test_degrades_to_curated_and_local_when_supabase_offline(
        self, app, client: AsyncClient
    ) -> None:
        # Supabase unconfigured → browse returns [] (no UGC). The route must NOT
        # error — it returns curated ∪ local instead.
        app.state.catalog_client = _StubMergeCatalog(
            ugc=[],
            local=[{"name": "local-agent", "description": "l", "version": "1.0.0"}],
        )
        app.state.skills_catalog = _StubGithubCatalog(
            entries=[
                {"name": "pdf-skill", "description": "p", "source_id": "kali",
                 "trust": "official", "metadata": {}, "repo_owner": "anthropics"},
            ]
        )

        resp = await client.get("/catalog/community")

        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()["results"]]
        assert "pdf-skill" in names      # curated survives
        assert "local-agent" in names    # local fallback survives
        # No exception, no UGC.
        assert all(c["source"] != "ugc" for c in resp.json()["results"])

    async def test_degrades_when_github_refresh_raises(
        self, app, client: AsyncClient
    ) -> None:
        # A GitHub refresh failure must not error the route — UGC still returns.
        app.state.catalog_client = _StubMergeCatalog(
            ugc=[{"slug": "weather-bot", "name": "Weather Bot", "description": "w"}],
        )
        app.state.skills_catalog = _StubGithubCatalog(raise_refresh=True)

        resp = await client.get("/catalog/community")

        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()["results"]]
        assert names == ["Weather Bot"]


class TestCommunityAccountRoutes:
    """WS-3 Task 3.3/3.5 — magic-link account routes (NOT OAuth)."""

    async def test_account_status_signed_out(
        self, app, client: AsyncClient
    ) -> None:
        identity = MagicMock()
        identity.current_account_id.return_value = None
        app.state.catalog_client = MagicMock(identity=identity)

        resp = await client.get("/community/account")

        assert resp.status_code == 200
        assert resp.json() == {"signed_in": False, "account_id": None}

    async def test_magic_link_requires_email(
        self, app, client: AsyncClient
    ) -> None:
        app.state.catalog_client = MagicMock()

        resp = await client.post("/community/account/magic-link", json={})

        assert resp.status_code == 400

    async def test_magic_link_passes_email_through(
        self, app, client: AsyncClient
    ) -> None:
        identity = MagicMock()
        identity.request_magic_link.return_value = {"status": "sent"}
        app.state.catalog_client = MagicMock(identity=identity)

        resp = await client.post(
            "/community/account/magic-link", json={"email": "a@b.ru"}
        )

        assert resp.status_code == 200
        assert resp.json() == {"status": "sent"}
        identity.request_magic_link.assert_called_once_with("a@b.ru")


class TestChatNoKeyHonestFallback:
    """A skip-key user (no AI key → provider error) must get an honest Russian
    prompt routing them to settings, never the English fallback text."""

    async def test_no_key_returns_russian_no_key_source(
        self, app, client: AsyncClient
    ) -> None:
        from kernel.llm_router import LLMResponse

        async def _error_route(self, request):  # type: ignore[no-untyped-def]
            return LLMResponse(
                text="I'm sorry, I couldn't process that request.",
                tool_calls=None,
                provider_used="error",
                latency_ms=0,
            )

        with patch("kernel.llm_router.LLMRouter.route", _error_route):
            resp = await client.post("/chat", json={"text": "привет"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "no-key"
        assert "I'm sorry" not in body["response"]
        assert "Настройки" in body["response"]
