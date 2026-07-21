"""OPUS-102 wiring-level tests: prove the ModelCoordinator is actually wired into
create_app's lifespan and the /tts // /voice/transcribe routes — not just green in
isolation (the project's recurring green-while-broken trap).

Uses COUNTING fakes monkeypatched onto the real load entry points, driven through
the real ASGI lifespan, so a mis-wired name / un-rewired route reddens here.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from kernel.main import create_app


async def _start_lifespan(app):  # type: ignore[no-untyped-def]
    started: asyncio.Event = asyncio.Event()
    shutdown_event: asyncio.Event = asyncio.Event()

    async def receive():  # type: ignore[no-untyped-def]
        if not started.is_set():
            return {"type": "lifespan.startup"}
        await shutdown_event.wait()
        return {"type": "lifespan.shutdown"}

    async def send(message):  # type: ignore[no-untyped-def]
        if message["type"] == "lifespan.startup.complete":
            started.set()

    task = asyncio.create_task(app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send))
    await started.wait()
    return task, shutdown_event


@pytest.fixture
async def app(tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path):  # type: ignore[no-untyped-def]
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
async def client(app):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class _Counter:
    """Fake TTS+STT load entry points with call counters + engine-truth state."""

    def __init__(self, *, tts_fail: Exception | None = None) -> None:
        self.tts_calls = 0
        self.stt_calls = 0
        self._tts_loaded = False
        self._tts_fail = tts_fail

    # tts_router.load_models / is_loaded
    def load_models(self) -> None:
        self.tts_calls += 1
        if self._tts_fail is not None:
            raise self._tts_fail
        self._tts_loaded = True

    def is_loaded(self) -> bool:
        return self._tts_loaded

    # transcribe_helper.get_or_create_stt
    def get_or_create_stt(self, app_state) -> object:  # type: ignore[no-untyped-def]
        self.stt_calls += 1
        stt = object()
        app_state.stt = stt
        return stt


def _patch_loaders(monkeypatch, counter: _Counter, *, prewarm: bool) -> None:
    import kernel.voice.transcribe_helper as th
    import kernel.voice.tts_router as tr

    if prewarm:
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)
    monkeypatch.setattr(tr, "load_models", counter.load_models)
    monkeypatch.setattr(tr, "is_loaded", counter.is_loaded)
    monkeypatch.setattr(th, "get_or_create_stt", counter.get_or_create_stt)


async def _make_app(monkeypatch, tmp_path, sample_agents_dir, sample_config_path):  # type: ignore[no-untyped-def]
    app = create_app(
        config_path=sample_config_path,
        agents_dir=sample_agents_dir,
        db_path=tmp_path / "test.db",
    )
    task, shutdown_event = await _start_lifespan(app)
    return app, task, shutdown_event


async def _poll_until(fn, timeout: float = 2.0) -> bool:
    for _ in range(int(timeout / 0.01)):
        if fn():
            return True
        await asyncio.sleep(0.01)
    return fn()


# ── readiness routes (default fixtures, KALI_SKIP_PREWARM=1) ──────────────────

class TestReadinessRoutes:
    async def test_live_is_instant_and_stateless(self, client: AsyncClient) -> None:
        resp = await client.get("/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "live"
        assert "version" in data

    async def test_ready_text_ready_true_with_voice_status(self, client: AsyncClient) -> None:
        resp = await client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["text_ready"] is True
        assert set(data["voice"]["models"]) == {"tts", "stt"}
        assert "voice" in data["voice"]  # overall key

    async def test_health_contract_unchanged(self, client: AsyncClient, monkeypatch) -> None:
        # Rust supervisor contract must survive OPUS-102.
        monkeypatch.setenv("KALI_DESKTOP_INSTANCE_ID", "wire-1")
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["desktop_instance_id"] == "wire-1"

    async def test_coordinator_registered_with_voice_models(self, app) -> None:  # type: ignore[no-untyped-def]
        coord = app.state.model_coordinator
        assert coord.has("tts") and coord.has("stt")


# ── prewarm + on-demand wiring (counting fakes, prewarm ON) ───────────────────

class TestPrewarmWiring:
    async def test_prewarm_loads_each_model_once_via_coordinator(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        counter = _Counter()
        _patch_loaders(monkeypatch, counter, prewarm=True)
        app, task, shutdown_event = await _make_app(
            monkeypatch, tmp_path, sample_agents_dir, sample_config_path
        )
        try:
            coord = app.state.model_coordinator
            ok = await _poll_until(
                lambda: coord.status("tts").state.value == "ready"
                and coord.status("stt").state.value == "ready"
            )
            assert ok, "prewarm did not drive both models to ready"
            assert counter.tts_calls == 1
            assert counter.stt_calls == 1
        finally:
            shutdown_event.set()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

    async def test_tts_route_goes_through_coordinator_and_dedups(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        counter = _Counter()
        _patch_loaders(monkeypatch, counter, prewarm=False)  # skip prewarm → isolate the route
        import kernel.voice.tts_router as tr

        monkeypatch.setattr(tr, "generate_audio", lambda *a, **k: (np.zeros(8, dtype=np.float32), 16000))
        monkeypatch.setattr(tr, "audio_to_wav_bytes", lambda audio, sr: b"RIFFwav")
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        app, task, shutdown_event = await _make_app(
            monkeypatch, tmp_path, sample_agents_dir, sample_config_path
        )
        try:
            # spy proves the ROUTE goes through the coordinator (not a direct load)
            coord = app.state.model_coordinator
            ensure_calls: list[str] = []
            _orig = coord.ensure

            async def _spy(name: str) -> None:
                ensure_calls.append(name)
                await _orig(name)

            coord.ensure = _spy  # type: ignore[method-assign]

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r1 = await c.post("/tts", json={"text": "привет"})
                r2 = await c.post("/tts", json={"text": "снова"})
            assert r1.status_code == 200 and r2.status_code == 200
            assert ensure_calls == ["tts", "tts"]  # every request routed via coordinator
            assert counter.tts_calls == 1  # single-flight → loaded exactly once
            assert coord.status("tts").state.value == "ready"
        finally:
            shutdown_event.set()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

    async def test_transcribe_route_ensures_stt_via_coordinator(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        counter = _Counter()
        _patch_loaders(monkeypatch, counter, prewarm=False)
        import base64

        import kernel.voice.transcribe_helper as th

        monkeypatch.setattr(th, "decode_and_resample", lambda b64, sr: (np.zeros(8, dtype=np.float32), 16000))

        class _Result:
            text = "ok"
            language = "ru"

        class _Stt:
            _model = None

            def transcribe(self, *a, **k):  # type: ignore[no-untyped-def]
                return _Result()

        # Cache-aware like the real single-flight get_or_create_stt: a second
        # caller (the route, after the coordinator ensure) sees app.state.stt and
        # does NOT reload — so the weight load happens exactly once.
        def _fake_get(app_state):  # type: ignore[no-untyped-def]
            existing = getattr(app_state, "stt", None)
            if existing is not None:
                return existing
            counter.stt_calls += 1
            app_state.stt = _Stt()
            return app_state.stt

        monkeypatch.setattr(th, "get_or_create_stt", _fake_get)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        app, task, shutdown_event = await _make_app(
            monkeypatch, tmp_path, sample_agents_dir, sample_config_path
        )
        try:
            coord = app.state.model_coordinator
            ensure_calls: list[str] = []
            _orig = coord.ensure

            async def _spy(name: str) -> None:
                ensure_calls.append(name)
                await _orig(name)

            coord.ensure = _spy  # type: ignore[method-assign]

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                audio_b64 = base64.b64encode(b"\x00\x00" * 8).decode()
                resp = await c.post("/voice/transcribe", json={"audio_b64": audio_b64})
            assert resp.status_code == 200
            assert resp.json()["text"] == "ok"
            assert ensure_calls == ["stt"]  # route ensured stt via coordinator
            assert counter.stt_calls == 1  # loaded once via coordinator ensure + cached
        finally:
            shutdown_event.set()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass


class TestEngineScoped:
    async def test_engine_rust_loads_nothing_in_python(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        # A Rust-owned voice engine must load NO voice model in Python — not at
        # boot (prewarm skipped) and not on-demand (route skips disabled).
        cfg = tmp_path / "kali.yaml"
        cfg.write_text("voice:\n  engine: rust\n", encoding="utf-8")
        counter = _Counter()
        _patch_loaders(monkeypatch, counter, prewarm=True)  # prewarm ON but must skip disabled
        import kernel.voice.tts_router as tr

        monkeypatch.setattr(tr, "generate_audio", lambda *a, **k: (np.zeros(8, dtype=np.float32), 16000))
        monkeypatch.setattr(tr, "audio_to_wav_bytes", lambda audio, sr: b"RIFFwav")

        app, task, shutdown_event = await _make_app(monkeypatch, tmp_path, sample_agents_dir, cfg)
        try:
            await asyncio.sleep(0.1)  # give any (wrongly-spawned) prewarm a chance
            coord = app.state.model_coordinator
            assert coord.status("tts").state.value == "disabled"
            assert coord.status("stt").state.value == "disabled"
            assert counter.tts_calls == 0 and counter.stt_calls == 0
            assert app.state.voice_pipeline is None

            # on-demand /tts must also NOT load under engine=rust
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.post("/tts", json={"text": "привет"})
                ready = (await c.get("/ready")).json()
            assert r.status_code == 200
            assert counter.tts_calls == 0  # route skipped the disabled model
            assert ready["voice"]["voice"] == "disabled"
        finally:
            shutdown_event.set()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass


class TestDegradedIsolation:
    async def test_tts_failure_keeps_text_ready_and_marks_voice_degraded(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        counter = _Counter(tts_fail=FileNotFoundError("no F5 weights offline"))
        _patch_loaders(monkeypatch, counter, prewarm=True)
        app, task, shutdown_event = await _make_app(
            monkeypatch, tmp_path, sample_agents_dir, sample_config_path
        )
        try:
            coord = app.state.model_coordinator
            ok = await _poll_until(lambda: coord.status("tts").state.value == "failed")
            assert ok, "tts should be FAILED after loader raised"
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                data = (await c.get("/ready")).json()
            assert data["text_ready"] is True  # text mode unaffected by voice failure
            assert data["voice"]["voice"] == "degraded"
        finally:
            shutdown_event.set()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
