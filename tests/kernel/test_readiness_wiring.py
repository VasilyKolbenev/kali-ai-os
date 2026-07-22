"""OPUS-102 wiring-level tests: prove the ModelCoordinator single owner is wired
into create_app's lifespan and the voice routes — driven through the real ASGI
lifespan with COUNTING fakes so a mis-wire reddens here (not just in isolation).
"""
from __future__ import annotations

import asyncio
import time
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

    t0 = time.perf_counter()
    task = asyncio.create_task(app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send))
    await started.wait()
    startup_secs = time.perf_counter() - t0
    return task, shutdown_event, startup_secs


class _VoiceFakes:
    """Counting fakes for every voice load path (Codex #1 requires counters on
    generate_audio + get_or_create_stt, not only load_models)."""

    def __init__(
        self,
        *,
        tts_delay: float = 0.0,
        tts_fail: Exception | None = None,
        torch_timing: float = 0.0,
    ) -> None:
        self.stt_instances = 0
        self.stt_loads = 0
        self.tts_load_calls = 0
        self.generate_calls = 0
        self.get_or_create_calls = 0
        self.order: list[str] = []
        self._tts_loaded = False
        self._tts_delay = tts_delay
        self._tts_fail = tts_fail
        self._torch_timing = torch_timing
        self._torch_ready = False
        self._vad_wake_delay = 0.0
        self._stt_delay = 0.0

    def install(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import kernel.torch_dep as torch_dep
        import kernel.voice.stt as stt_mod
        import kernel.voice.transcribe_helper as th
        import kernel.voice.tts_router as tr
        import kernel.voice.vad as vad_mod
        import kernel.voice.wake_word as ww_mod

        fakes = self

        # Deterministic torch dep — no real cold import (Codex #4): fast, flagged.
        self._torch_ready = False

        def _torch_load():  # type: ignore[no-untyped-def]
            time.sleep(self._torch_timing)
            self._torch_ready = True
            self.order.append("torch")

        monkeypatch.setattr(torch_dep, "load", _torch_load)
        monkeypatch.setattr(torch_dep, "is_ready", lambda: fakes._torch_ready)

        # STT: count instances + loads; is_loaded reflects fake load.
        _orig_init = stt_mod.SpeechToText.__init__

        def _stt_init(self, *a, **k):  # type: ignore[no-untyped-def]
            fakes.stt_instances += 1
            _orig_init(self, *a, **k)

        def _stt_load(self):  # type: ignore[no-untyped-def]
            fakes.stt_loads += 1
            if fakes._stt_delay:
                time.sleep(fakes._stt_delay)
            self._loaded = True
            if "stt" not in fakes.order:
                fakes.order.append("stt")

        monkeypatch.setattr(stt_mod.SpeechToText, "__init__", _stt_init)
        monkeypatch.setattr(stt_mod.SpeechToText, "load", _stt_load)

        # count get_or_create_stt itself (route + coordinator both funnel here)
        _orig_goc = th.get_or_create_stt

        def _goc(app_state):  # type: ignore[no-untyped-def]
            fakes.get_or_create_calls += 1
            return _orig_goc(app_state)

        monkeypatch.setattr(th, "get_or_create_stt", _goc)

        # VAD / wake: fake loads with configurable timing
        def _vw_load(self):  # type: ignore[no-untyped-def]
            if fakes._vad_wake_delay:
                time.sleep(fakes._vad_wake_delay)
            self._loaded = True

        monkeypatch.setattr(vad_mod.VoiceActivityDetector, "load", _vw_load)
        monkeypatch.setattr(ww_mod.WakeWordDetector, "load", _vw_load)

        # TTS
        def _tts_load():  # type: ignore[no-untyped-def]
            fakes.tts_load_calls += 1
            if fakes._tts_delay:
                time.sleep(fakes._tts_delay)
            if fakes._tts_fail is not None:
                raise fakes._tts_fail
            fakes._tts_loaded = True
            fakes.order.append("tts")

        monkeypatch.setattr(tr, "load_models", _tts_load)
        monkeypatch.setattr(tr, "is_loaded", lambda: fakes._tts_loaded)

        def _gen(*a, **k):  # type: ignore[no-untyped-def]
            fakes.generate_calls += 1
            return (np.zeros(8, dtype=np.float32), 16000)

        monkeypatch.setattr(tr, "generate_audio", _gen)
        monkeypatch.setattr(tr, "audio_to_wav_bytes", lambda audio, sr: b"RIFFwav")
        # avoid the CUDA-warmup F5 branch
        monkeypatch.setattr(tr, "get_provider", lambda: "elevenlabs")


async def _make_app(tmp_path, agents_dir, config_path):  # type: ignore[no-untyped-def]
    app = create_app(config_path=config_path, agents_dir=agents_dir, db_path=tmp_path / "test.db")
    task, shutdown_event, startup_secs = await _start_lifespan(app)
    return app, task, shutdown_event, startup_secs


async def _teardown(task, shutdown_event) -> None:  # type: ignore[no-untyped-def]
    shutdown_event.set()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except (TimeoutError, asyncio.CancelledError):
        pass


async def _poll_until(fn, timeout: float = 2.0) -> bool:  # type: ignore[no-untyped-def]
    for _ in range(int(timeout / 0.01)):
        if fn():
            return True
        await asyncio.sleep(0.01)
    return fn()


# ── readiness routes (default fixtures, KALI_SKIP_PREWARM=1) ──────────────────

class TestReadinessRoutes:
    async def test_live_is_instant_and_stateless(self, client: AsyncClient) -> None:
        data = (await client.get("/live")).json()
        assert data["status"] == "live"
        assert "version" in data

    async def test_ready_text_ready_true_with_voice_status(self, client: AsyncClient) -> None:
        data = (await client.get("/ready")).json()
        assert data["text_ready"] is True
        assert {"torch", "vad", "wake", "stt", "tts"} <= set(data["voice"]["models"])
        assert "voice" in data["voice"]

    async def test_health_contract_unchanged(self, client: AsyncClient, monkeypatch) -> None:
        monkeypatch.setenv("KALI_DESKTOP_INSTANCE_ID", "wire-1")
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["desktop_instance_id"] == "wire-1"

    async def test_coordinator_registers_torch_and_voice_components(self, app) -> None:  # type: ignore[no-untyped-def]
        coord = app.state.model_coordinator
        for m in ("torch", "vad", "wake", "stt", "tts"):
            assert coord.has(m)


# ── prewarm + single-STT ownership (default engine=python) ───────────────────

class TestOwnership:
    async def test_default_config_single_stt_one_load(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        fakes = _VoiceFakes()
        fakes.install(monkeypatch)
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)  # prewarm ON
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            coord = app.state.model_coordinator
            assert await _poll_until(lambda: coord.status("stt").state.value == "ready")
            # exactly ONE SpeechToText instance (pipeline._stt, shared as app.state.stt)
            assert app.state.stt is app.state.voice_pipeline._stt
            assert fakes.stt_instances == 1
            assert fakes.stt_loads == 1
        finally:
            await _teardown(task, sd)

    async def test_prewarm_loads_stt_and_tts_via_coordinator(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        fakes = _VoiceFakes()
        fakes.install(monkeypatch)
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            coord = app.state.model_coordinator
            ok = await _poll_until(
                lambda: coord.status("stt").state.value == "ready"
                and coord.status("tts").state.value == "ready"
            )
            assert ok
            assert fakes.tts_load_calls == 1
            assert fakes.stt_loads == 1
        finally:
            await _teardown(task, sd)

    async def test_voice_start_non_blocking_via_coordinator(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        fakes = _VoiceFakes()
        fakes.install(monkeypatch)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")  # isolate /voice/start
        # never call the (blocking) pipeline.load_models
        import kernel.voice.pipeline as pl

        def _boom(self):  # type: ignore[no-untyped-def]
            raise AssertionError("pipeline.load_models must not be called (OPUS-102)")

        monkeypatch.setattr(pl.VoicePipeline, "load_models", _boom)
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.post("/voice/start")
            assert r.status_code == 200
            assert r.json()["status"] == "started"
            assert fakes.stt_instances == 1  # one STT even after start
        finally:
            await _teardown(task, sd)


# ── fail-closed on-demand routes ─────────────────────────────────────────────

class TestFailClosed:
    async def test_tts_route_dedups_and_synthesizes_when_ready(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        fakes = _VoiceFakes()
        fakes.install(monkeypatch)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            coord = app.state.model_coordinator
            calls: list[str] = []
            _orig = coord.ensure_ready

            async def _spy(name, **kw):  # type: ignore[no-untyped-def]
                calls.append(name)
                return await _orig(name, **kw)

            coord.ensure_ready = _spy  # type: ignore[method-assign]
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r1 = await c.post("/tts", json={"text": "привет"})
                r2 = await c.post("/tts", json={"text": "снова"})
            assert r1.status_code == 200 and r2.status_code == 200
            assert calls.count("tts") == 2  # every request routed via the waiting api
            assert fakes.tts_load_calls == 1  # single-flight load
            assert fakes.generate_calls == 2
        finally:
            await _teardown(task, sd)

    async def test_tts_failure_returns_503_and_no_generate(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        fakes = _VoiceFakes(tts_fail=FileNotFoundError("no F5 weights"))
        fakes.install(monkeypatch)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.post("/tts", json={"text": "привет"})
            assert r.status_code == 503
            assert r.json()["reason"] == "model_unavailable"
            assert fakes.tts_load_calls == 1  # exactly one load attempt
            assert fakes.generate_calls == 0  # fail-closed: no synthesis on failure
        finally:
            await _teardown(task, sd)


class TestEngineScoped:
    async def test_engine_rust_routes_409_and_load_nothing(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        import base64

        cfg = tmp_path / "kali.yaml"
        cfg.write_text("voice:\n  engine: rust\n", encoding="utf-8")
        fakes = _VoiceFakes()
        fakes.install(monkeypatch)
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, cfg)
        try:
            await asyncio.sleep(0.1)
            coord = app.state.model_coordinator
            assert coord.status("tts").state.value == "disabled"
            assert coord.status("stt").state.value == "disabled"
            assert app.state.voice_pipeline is None

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r_tts = await c.post("/tts", json={"text": "привет"})
                audio_b64 = base64.b64encode(b"\x00\x00" * 8).decode()
                r_stt = await c.post("/voice/transcribe", json={"audio_b64": audio_b64})
                ready = (await c.get("/ready")).json()
            assert r_tts.status_code == 409 and r_tts.json()["reason"] == "engine_owned_by_rust"
            assert r_stt.status_code == 409 and r_stt.json()["reason"] == "engine_owned_by_rust"
            # counters on BOTH generation and STT init (Codex #1)
            assert fakes.generate_calls == 0
            assert fakes.get_or_create_calls == 0
            assert fakes.tts_load_calls == 0
            assert fakes.stt_instances == 0
            assert ready["voice"]["voice"] == "disabled"
        finally:
            await _teardown(task, sd)


class TestStartupSLA:
    async def test_slow_loader_does_not_block_startup(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        # A 45s TTS load must NOT delay lifespan startup / /live; /ready stays
        # text_ready=true with voice=loading.
        fakes = _VoiceFakes(tts_delay=45.0)
        fakes.install(monkeypatch)
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)
        app, task, sd, startup_secs = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            assert startup_secs <= 1.0, f"lifespan startup took {startup_secs:.2f}s"
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                t0 = time.perf_counter()
                live = await c.get("/live")
                live_secs = time.perf_counter() - t0
                ready = (await c.get("/ready")).json()
            assert live.status_code == 200 and live_secs <= 1.0
            assert ready["text_ready"] is True
            assert ready["voice"]["voice"] in ("loading", "degraded")
        finally:
            await _teardown(task, sd)

    async def test_torch_loads_before_voice_models(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path
    ) -> None:
        # deps ordering: torch (deterministic fake, 50ms) must complete before
        # tts starts (frozen race guard).
        fakes = _VoiceFakes(torch_timing=0.05)
        fakes.install(monkeypatch)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, sample_config_path)
        try:
            from kernel.model_coordinator import ModelOutcome

            coord = app.state.model_coordinator
            assert await coord.ensure_ready("tts") is ModelOutcome.READY
            assert fakes.order.index("torch") < fakes.order.index("tts")
        finally:
            await _teardown(task, sd)


class TestShippingAutoStart:
    async def test_autostart_with_parallel_prewarm_starts_pipeline_once(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        # Codex #1 regression. SHIPPING config (explicit): engine=python,
        # auto_start=true, mode=wake_word. torch=50ms, vad/wake=80ms, stt/tts=600ms.
        # auto-start runs and, with a parallel prewarm(stt,tts), must drive ALL
        # components READY, start the pipeline exactly once, start_error=None —
        # via the WAITING api (shared completion), not a LOADING fast-path.
        cfg = tmp_path / "kali.yaml"
        cfg.write_text(
            "voice:\n  engine: python\n  auto_start: true\n  mode: wake_word\n",
            encoding="utf-8",
        )
        fakes = _VoiceFakes(torch_timing=0.05, tts_delay=0.6)
        fakes._vad_wake_delay = 0.08
        fakes._stt_delay = 0.6
        fakes.install(monkeypatch)
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)  # prewarm parallel with auto-start

        import kernel.voice.pipeline as pl

        starts = {"n": 0}

        async def _fake_start(self):  # type: ignore[no-untyped-def]
            starts["n"] += 1
            self._started = True

        monkeypatch.setattr(pl.VoicePipeline, "start", _fake_start)

        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, cfg)
        try:
            await asyncio.wait_for(app.state._voice_bg_task, timeout=8.0)
            coord = app.state.model_coordinator
            for m in ("torch", "vad", "wake", "stt", "tts"):
                assert coord.status(m).state.value == "ready", m
            assert starts["n"] == 1  # pipeline started exactly once
            assert app.state.voice_start_error is None
        finally:
            await _teardown(task, sd)


class TestProbeConsistency:
    async def test_vad_swallowed_load_failure_blocks_pipeline_start(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        # P1-1: VAD.load() returns normally but leaves is_loaded False (swallowed
        # torch.hub failure). The component is FAILED, so auto-start must NOT start
        # the pipeline and /ready must be degraded.
        cfg = tmp_path / "kali.yaml"
        cfg.write_text(
            "voice:\n  engine: python\n  auto_start: true\n  mode: wake_word\n",
            encoding="utf-8",
        )
        fakes = _VoiceFakes(torch_timing=0.02)
        fakes.install(monkeypatch)
        import kernel.voice.pipeline as pl
        import kernel.voice.vad as vad_mod

        # swallowed failure: returns without flipping is_loaded
        monkeypatch.setattr(vad_mod.VoiceActivityDetector, "load", lambda self: None)
        starts = {"n": 0}

        async def _fake_start(self):  # type: ignore[no-untyped-def]
            starts["n"] += 1
            self._started = True

        monkeypatch.setattr(pl.VoicePipeline, "start", _fake_start)
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)

        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, cfg)
        try:
            await asyncio.wait_for(app.state._voice_bg_task, timeout=8.0)
            coord = app.state.model_coordinator
            assert coord.status("vad").state.value == "failed"
            assert coord.status("vad").error == "loader_completed_probe_false"
            assert starts["n"] == 0  # pipeline NOT started on a failed component
            assert app.state.voice_start_error is not None
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                ready = (await c.get("/ready")).json()
            assert ready["voice"]["voice"] == "degraded"
        finally:
            await _teardown(task, sd)

    async def test_ready_shows_timeout_not_eternal_loading(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        # P1-2: a component whose load overruns its deadline shows TIMEOUT in /ready
        # (voice degraded), not eternal loading.
        cfg = tmp_path / "kali.yaml"
        cfg.write_text("voice:\n  engine: python\n  auto_start: false\n", encoding="utf-8")
        fakes = _VoiceFakes(tts_delay=1.0)  # slow → overruns the short deadline
        fakes.install(monkeypatch)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, cfg)
        try:
            from kernel.model_coordinator import ModelOutcome

            coord = app.state.model_coordinator
            assert await coord.ensure_ready("tts", timeout=0.05) is ModelOutcome.TIMEOUT
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                ready = (await c.get("/ready")).json()
            assert ready["voice"]["models"]["tts"]["state"] == "timeout"
            assert ready["voice"]["voice"] == "degraded"
        finally:
            await _teardown(task, sd)


class TestWarmup:
    async def test_warmup_synth_fires_after_tts_ready(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        # Regression for the review MEDIUM: the warmup used the fail-fast ensure()
        # (returns LOADING) then gated on status==ready → the micro-synth never
        # fired. With ensure_ready it fires once TTS is genuinely loaded.
        cfg = tmp_path / "kali.yaml"
        cfg.write_text("voice:\n  engine: python\n  auto_start: false\n", encoding="utf-8")
        # Slow TTS so the warmup observes LOADING at check time: with the fail-fast
        # ensure() the synth would be skipped (no-op); ensure_ready waits → fires.
        fakes = _VoiceFakes(tts_delay=0.3)
        fakes.install(monkeypatch)
        import kernel.voice.tts_engine_f5 as f5
        import kernel.voice.tts_router as tr

        monkeypatch.setattr(tr, "get_provider", lambda: tr.PROVIDER_F5)  # force the F5 warmup branch
        warmups = {"n": 0}
        monkeypatch.setattr(f5, "generate_audio", lambda text: warmups.__setitem__("n", warmups["n"] + 1))
        monkeypatch.delenv("KALI_SKIP_PREWARM", raising=False)

        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, cfg)
        try:
            await asyncio.wait_for(app.state._tts_warmup_task, timeout=5.0)
            assert warmups["n"] == 1  # warmup synth fired exactly once after ready
        finally:
            await _teardown(task, sd)


class TestChatAutoSpeak:
    async def _run_chat(self, monkeypatch, tmp_path, agents_dir, config_path):  # type: ignore[no-untyped-def]
        import kernel.routers.chat as chat_mod
        import kernel.voice.jarvis_sounds as js
        import kernel.voice.tts_router as tr

        calls = {"by_sentence": 0}

        async def _fake_by_sentence(text):  # type: ignore[no-untyped-def]
            calls["by_sentence"] += 1
            yield (np.zeros(8, dtype=np.float32), 16000)

        monkeypatch.setattr(js, "should_use_clip", lambda text: None)  # force TTS path
        monkeypatch.setattr(tr, "generate_audio_by_sentence", _fake_by_sentence)
        monkeypatch.setattr(chat_mod, "_play_audio", lambda audio, sr: None)
        # short-circuit the LLM so /chat returns fast with a speakable response
        monkeypatch.setattr(chat_mod, "_chat_logic", lambda request: _resp())
        return calls

    async def test_engine_rust_no_python_tts(
        self, monkeypatch, tmp_path: Path, sample_agents_dir: Path
    ) -> None:
        cfg = tmp_path / "kali.yaml"
        cfg.write_text("voice:\n  engine: rust\n", encoding="utf-8")
        fakes = _VoiceFakes()
        fakes.install(monkeypatch)
        monkeypatch.setenv("KALI_SKIP_PREWARM", "1")
        calls = await self._run_chat(monkeypatch, tmp_path, sample_agents_dir, cfg)
        app, task, sd, _ = await _make_app(tmp_path, sample_agents_dir, cfg)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                await c.post("/chat", json={"message": "привет"})
            for t in list(app.state._speak_tasks):
                await asyncio.wait_for(t, timeout=2.0)
            assert calls["by_sentence"] == 0  # no generation under engine=rust
            assert fakes.tts_load_calls == 0  # no Python TTS load
        finally:
            await _teardown(task, sd)


async def _resp():  # type: ignore[no-untyped-def]
    return {"response": "Готово, сэр, задача выполнена успешно."}


# ── fixtures reused from the default lifespan pattern ─────────────────────────

@pytest.fixture
async def app(tmp_path: Path, sample_agents_dir: Path, sample_config_path: Path):  # type: ignore[no-untyped-def]
    application = create_app(
        config_path=sample_config_path, agents_dir=sample_agents_dir, db_path=tmp_path / "test.db"
    )
    task, shutdown_event, _ = await _start_lifespan(application)
    yield application
    await _teardown(task, shutdown_event)


@pytest.fixture
async def client(app):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
