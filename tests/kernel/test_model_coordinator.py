"""OPUS-102 coordinator: daemon-thread single-flight, typed outcomes, deps.

Fake loaders only (no real ML). Load-once proven by a call counter; ordering by
a shared log; state derived from the engine-truth probe.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from kernel.model_coordinator import ModelCoordinator, ModelOutcome, ModelState


class FakeModel:
    def __init__(self, *, delay: float = 0.0, fail: Exception | None = None, log: list | None = None, name: str = "m") -> None:
        self.loaded = False
        self.calls = 0
        self.delay = delay
        self.fail = fail
        self._log = log
        self._name = name

    def load(self) -> None:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        self.loaded = True
        if self._log is not None:
            self._log.append(self._name)

    def probe(self) -> bool:
        return self.loaded


def _coord(**models: FakeModel):  # type: ignore[no-untyped-def]
    c = ModelCoordinator(default_timeout=5.0)
    for name, fake in models.items():
        c.register(name, fake.load, fake.probe, voice_component=True)
    return c, models


async def test_single_flight_loads_exactly_once() -> None:
    fake = FakeModel(delay=0.05)
    c, _ = _coord(tts=fake)
    outs = await asyncio.gather(*(c.ensure("tts") for _ in range(8)))
    assert fake.calls == 1  # single-flight: exactly one loader invocation
    # F4: concurrent callers are non-blocking → one drives the load (READY), the
    # rest see it in-flight (LOADING); none is FAILED/TIMEOUT.
    assert all(o in (ModelOutcome.READY, ModelOutcome.LOADING) for o in outs)
    assert ModelOutcome.READY in outs
    assert c.status("tts").state is ModelState.READY


async def test_failure_returns_failed_and_voice_degraded() -> None:
    fake = FakeModel(fail=RuntimeError("boom"))
    c, _ = _coord(tts=fake)
    assert await c.ensure("tts") is ModelOutcome.FAILED
    assert c.status("tts").state is ModelState.FAILED
    assert c.snapshot()["voice"] == "degraded"


async def test_offline_no_cache_does_not_hang() -> None:
    fake = FakeModel(fail=FileNotFoundError("missing"))
    c, _ = _coord(stt=fake)
    out = await asyncio.wait_for(c.ensure("stt"), timeout=2.0)
    assert out is ModelOutcome.FAILED


async def test_state_derived_from_probe_even_if_loaded_directly() -> None:
    fake = FakeModel()
    c, _ = _coord(tts=fake)
    assert c.status("tts").state is ModelState.NOT_STARTED
    fake.loaded = True  # loaded elsewhere (pipeline / /voice/start)
    assert c.status("tts").state is ModelState.READY
    assert await c.ensure("tts") is ModelOutcome.READY
    assert fake.calls == 0  # probe short-circuit, no redundant load


async def test_retry_after_failure_recovers() -> None:
    fake = FakeModel(fail=RuntimeError("transient"))
    c, _ = _coord(tts=fake)
    assert await c.ensure("tts") is ModelOutcome.FAILED
    fake.fail = None
    assert await c.ensure("tts") is ModelOutcome.READY
    assert fake.calls == 2


async def test_disabled_is_fail_closed_no_load() -> None:
    fake = FakeModel()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("tts", fake.load, fake.probe, disabled=True, voice_component=True)
    assert c.status("tts").state is ModelState.DISABLED
    c.prewarm(["tts"])
    await asyncio.sleep(0.02)
    assert fake.calls == 0  # prewarm skipped
    # Codex #1: on-demand ensure is ALSO fail-closed — never loads a disabled model
    assert await c.ensure("tts") is ModelOutcome.DISABLED
    assert fake.calls == 0


async def test_deps_load_to_completion_before_dependent() -> None:
    log: list[str] = []
    torch = FakeModel(delay=0.05, log=log, name="torch")
    tts = FakeModel(log=log, name="tts")
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    assert await c.ensure("tts") is ModelOutcome.READY
    assert log == ["torch", "tts"]  # torch finished before tts started


async def test_dep_failure_fails_dependent() -> None:
    torch = FakeModel(fail=RuntimeError("no torch"))
    tts = FakeModel()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    assert await c.ensure("tts") is ModelOutcome.FAILED
    assert tts.calls == 0  # dependent never loaded when dep failed


async def test_self_dependency_rejected() -> None:
    c = ModelCoordinator()
    with pytest.raises(ValueError, match="itself"):
        c.register("x", lambda: None, lambda: True, deps=("x",))


async def test_timeout_reports_loading_and_no_second_loader() -> None:
    # A load that outruns the timeout: outcome TIMEOUT, worker still alive →
    # status LOADING, and a concurrent caller does NOT start a 2nd loader.
    release = threading.Event()

    class _Slow:
        def __init__(self) -> None:
            self.calls = 0
            self.loaded = False

        def load(self) -> None:
            self.calls += 1
            release.wait(5.0)
            self.loaded = True

        def probe(self) -> bool:
            return self.loaded

    slow = _Slow()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("stt", slow.load, slow.probe, timeout=0.1, voice_component=True)
    try:
        assert await c.ensure("stt") is ModelOutcome.TIMEOUT
        assert c.status("stt").state is ModelState.LOADING  # worker still alive
        assert await c.ensure("stt") is ModelOutcome.LOADING  # no 2nd loader
        assert slow.calls == 1
    finally:
        release.set()
        await asyncio.sleep(0.05)


async def test_shutdown_cancels_inflight_wrappers_no_orphan_task() -> None:
    fake = FakeModel(delay=1.0)
    c, _ = _coord(tts=fake)
    c.prewarm(["tts"])
    await asyncio.sleep(0.05)
    assert c.inflight_count() == 1
    await c.shutdown()
    assert c.inflight_count() == 0


async def test_snapshot_shape_and_voice_overall() -> None:
    tts = FakeModel()
    stt = FakeModel()
    c, _ = _coord(tts=tts, stt=stt)
    snap = c.snapshot()
    assert set(snap["models"]) == {"tts", "stt"}
    assert snap["voice"] in {"idle", "loading", "ready", "degraded", "disabled"}
    await c.ensure("tts")
    await c.ensure("stt")
    assert c.snapshot()["voice"] == "ready"
