"""OPUS-102 coordinator: shared single-flight completion + bounded waiting API.

Fake loaders (no ML). `ensure_ready` waits the shared completion (bounded);
`ensure` is a fail-fast background kick. Load-once proven by a call counter.
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


async def test_concurrent_ensure_ready_shares_one_load() -> None:
    fake = FakeModel(delay=0.05)
    c, _ = _coord(tts=fake)
    outs = await asyncio.gather(*(c.ensure_ready("tts") for _ in range(8)))
    assert fake.calls == 1  # shared completion: exactly one loader
    assert all(o is ModelOutcome.READY for o in outs)  # all callers wait the SAME load
    assert c.status("tts").state is ModelState.READY


async def test_ensure_is_failfast_background_kick() -> None:
    fake = FakeModel(delay=0.1)
    c, _ = _coord(tts=fake)
    out = await c.ensure("tts")  # returns LOADING immediately, load runs in background
    assert out is ModelOutcome.LOADING
    assert await _poll(lambda: c.status("tts").state is ModelState.READY)
    assert fake.calls == 1


async def _poll(fn, timeout: float = 2.0) -> bool:  # type: ignore[no-untyped-def]
    for _ in range(int(timeout / 0.01)):
        if fn():
            return True
        await asyncio.sleep(0.01)
    return fn()


async def test_failure_returns_failed_and_voice_degraded() -> None:
    fake = FakeModel(fail=RuntimeError("boom"))
    c, _ = _coord(tts=fake)
    assert await c.ensure_ready("tts") is ModelOutcome.FAILED
    assert await _poll(lambda: c.status("tts").state is ModelState.FAILED)
    assert c.snapshot()["voice"] == "degraded"


async def test_offline_no_cache_does_not_hang() -> None:
    fake = FakeModel(fail=FileNotFoundError("missing"))
    c, _ = _coord(stt=fake)
    out = await asyncio.wait_for(c.ensure_ready("stt"), timeout=2.0)
    assert out is ModelOutcome.FAILED


async def test_state_derived_from_probe_even_if_loaded_directly() -> None:
    fake = FakeModel()
    c, _ = _coord(tts=fake)
    assert c.status("tts").state is ModelState.NOT_STARTED
    fake.loaded = True  # loaded elsewhere (pipeline / /voice/start)
    assert c.status("tts").state is ModelState.READY
    assert await c.ensure_ready("tts") is ModelOutcome.READY
    assert fake.calls == 0  # probe short-circuit, no redundant load


async def test_retry_after_failure_recovers() -> None:
    fake = FakeModel(fail=RuntimeError("transient"))
    c, _ = _coord(tts=fake)
    assert await c.ensure_ready("tts") is ModelOutcome.FAILED
    fake.fail = None
    assert await c.ensure_ready("tts") is ModelOutcome.READY
    assert fake.calls == 2


async def test_disabled_is_fail_closed_no_load() -> None:
    fake = FakeModel()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("tts", fake.load, fake.probe, disabled=True, voice_component=True)
    assert c.status("tts").state is ModelState.DISABLED
    c.prewarm(["tts"])
    await asyncio.sleep(0.02)
    assert fake.calls == 0
    assert await c.ensure("tts") is ModelOutcome.DISABLED
    assert await c.ensure_ready("tts") is ModelOutcome.DISABLED
    assert fake.calls == 0


async def test_deps_load_to_completion_before_dependent() -> None:
    log: list[str] = []
    torch = FakeModel(delay=0.05, log=log, name="torch")
    tts = FakeModel(log=log, name="tts")
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    assert await c.ensure_ready("tts") is ModelOutcome.READY
    assert log == ["torch", "tts"]


async def test_concurrent_dependents_share_slow_dep_both_ready() -> None:
    # Two dependents pulling the SAME slow dep concurrently must BOTH reach READY
    # via the shared completion (regression for the LOADING-race).
    log: list[str] = []
    torch = FakeModel(delay=0.1, log=log, name="torch")
    stt = FakeModel(log=log, name="stt")
    tts = FakeModel(log=log, name="tts")
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe)
    c.register("stt", stt.load, stt.probe, deps=("torch",), voice_component=True)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    outs = await asyncio.gather(c.ensure_ready("stt"), c.ensure_ready("tts"))
    assert outs == [ModelOutcome.READY, ModelOutcome.READY]
    assert torch.calls == 1
    assert log[0] == "torch"


async def test_dep_failure_fails_dependent() -> None:
    torch = FakeModel(fail=RuntimeError("no torch"))
    tts = FakeModel()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    assert await c.ensure_ready("tts") is ModelOutcome.FAILED
    assert tts.calls == 0


async def test_bounded_dep_blocked_torch_times_out_and_dependent_not_started() -> None:
    # Codex #2: a blocked dep must not hang the dependent; with a small dep
    # timeout, ensure_ready(tts) returns bounded and tts's loader is never called.
    # The whole test is watchdogged so a mechanism hang reds THIS test, not the suite.
    release = threading.Event()

    class _Blocked:
        def __init__(self) -> None:
            self.calls = 0

        def load(self) -> None:
            self.calls += 1
            release.wait(10.0)

        def probe(self) -> bool:
            return False

    torch = _Blocked()
    tts = FakeModel()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe, timeout=0.1)  # bounded dep deadline
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    try:
        out = await asyncio.wait_for(c.ensure_ready("tts"), timeout=2.0)  # watchdog
        assert out in (ModelOutcome.FAILED, ModelOutcome.TIMEOUT)
        assert tts.calls == 0  # dependent never started
        assert torch.calls == 1  # dep loader started once, no 2nd loader
    finally:
        release.set()
        await asyncio.sleep(0.05)


async def test_self_dependency_rejected() -> None:
    c = ModelCoordinator()
    with pytest.raises(ValueError, match="itself"):
        c.register("x", lambda: None, lambda: True, deps=("x",))


async def test_wait_timeout_keeps_worker_and_no_second_loader() -> None:
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
    c.register("stt", slow.load, slow.probe, voice_component=True)
    try:
        assert await c.ensure_ready("stt", timeout=0.1) is ModelOutcome.TIMEOUT
        assert c.status("stt").state is ModelState.LOADING  # worker still alive
        assert await c.ensure_ready("stt", timeout=0.1) is ModelOutcome.TIMEOUT
        assert slow.calls == 1  # shared load — no 2nd loader
    finally:
        release.set()
        await asyncio.sleep(0.05)


async def test_shutdown_clears_task_wrappers_no_orphan() -> None:
    # prewarm's ensure is a fast background kick (the load runs on a daemon thread,
    # abandoned at shutdown — see the process-level SLA test). shutdown() must
    # leave no lingering asyncio task wrapper.
    fake = FakeModel(delay=1.0)
    c, _ = _coord(tts=fake)
    c.prewarm(["tts"])
    await asyncio.sleep(0.02)
    await c.shutdown()
    assert c.inflight_count() == 0


async def test_snapshot_shape_and_voice_overall() -> None:
    tts = FakeModel()
    stt = FakeModel()
    c, _ = _coord(tts=tts, stt=stt)
    snap = c.snapshot()
    assert set(snap["models"]) == {"tts", "stt"}
    assert snap["voice"] in {"idle", "loading", "ready", "degraded", "disabled"}
    await c.ensure_ready("tts")
    await c.ensure_ready("stt")
    assert c.snapshot()["voice"] == "ready"
