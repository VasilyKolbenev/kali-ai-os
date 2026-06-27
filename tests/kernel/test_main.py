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
