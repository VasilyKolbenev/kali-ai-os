"""OPUS-102: ModelCoordinator — single-flight, observable, engine-scoped.

Fake loaders only (no real ML). Single-flight/load-once is proven by a call
counter; state is derived from the engine-truth probe (F3).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from kernel.model_coordinator import ModelCoordinator, ModelState


class FakeModel:
    """Stand-in for a real weight loader + its engine-truth probe."""

    def __init__(self, *, delay: float = 0.0, fail: Exception | None = None) -> None:
        self.loaded = False
        self.calls = 0
        self.delay = delay
        self.fail = fail

    def load(self) -> None:  # blocking, run via to_thread
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        self.loaded = True

    def probe(self) -> bool:
        return self.loaded


def _coord(**models: FakeModel) -> tuple[ModelCoordinator, dict[str, FakeModel]]:
    c = ModelCoordinator(default_timeout=5.0)
    for name, fake in models.items():
        c.register(name, fake.load, fake.probe)
    return c, models


async def test_single_flight_loads_exactly_once() -> None:
    fake = FakeModel(delay=0.05)
    c, _ = _coord(tts=fake)
    await asyncio.gather(*(c.ensure("tts") for _ in range(8)))
    assert fake.calls == 1
    assert c.status("tts").state is ModelState.READY


async def test_failure_marks_failed_and_voice_degraded() -> None:
    fake = FakeModel(fail=RuntimeError("boom"))
    c, _ = _coord(tts=fake)
    await c.ensure("tts")  # ensure swallows → FAILED, does not raise
    st = c.status("tts")
    assert st.state is ModelState.FAILED
    assert "boom" in (st.error or "")
    assert c.snapshot()["voice"] == "degraded"


async def test_offline_no_cache_does_not_hang() -> None:
    fake = FakeModel(fail=FileNotFoundError("model missing"))
    c, _ = _coord(stt=fake)
    await asyncio.wait_for(c.ensure("stt"), timeout=2.0)  # must return, not hang
    assert c.status("stt").state is ModelState.FAILED


async def test_state_derived_from_probe_even_if_loaded_directly() -> None:
    # F3: a direct load (bypassing the coordinator) flips probe → status READY,
    # never a stale NOT_STARTED that would report "degraded" while voice works.
    fake = FakeModel()
    c, _ = _coord(tts=fake)
    assert c.status("tts").state is ModelState.NOT_STARTED
    fake.loaded = True  # someone else (pipeline / /voice/start) loaded it
    assert c.status("tts").state is ModelState.READY


async def test_retry_after_failure_recovers() -> None:
    fake = FakeModel(fail=RuntimeError("transient"))
    c, _ = _coord(tts=fake)
    await c.ensure("tts")
    assert c.status("tts").state is ModelState.FAILED
    fake.fail = None  # transient cleared
    await c.ensure("tts")
    assert c.status("tts").state is ModelState.READY
    assert fake.calls == 2


async def test_shutdown_cancels_inflight_wrappers_no_orphan_task() -> None:
    fake = FakeModel(delay=1.0)  # still loading when we shut down
    c, _ = _coord(tts=fake)
    c.prewarm(["tts"])
    await asyncio.sleep(0.05)  # let the task start
    assert c.inflight_count() == 1
    await c.shutdown()
    # honest guarantee: the asyncio wrappers are cancelled+awaited, none orphaned.
    # (A load already inside a worker thread runs to completion — not asserted here.)
    assert c.inflight_count() == 0


async def test_disabled_suppresses_prewarm_but_ensure_still_loads() -> None:
    # F6: engine=rust marks the model disabled → prewarm skips; an explicit
    # on-demand ensure still loads (DISABLED → LOADING → READY).
    fake = FakeModel()
    c = ModelCoordinator(default_timeout=5.0)
    c.register("tts", fake.load, fake.probe, disabled=True)
    assert c.status("tts").state is ModelState.DISABLED
    c.prewarm(["tts"])
    await asyncio.sleep(0.02)
    assert fake.calls == 0  # prewarm suppressed
    await c.ensure("tts")
    assert fake.calls == 1
    assert c.status("tts").state is ModelState.READY


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
