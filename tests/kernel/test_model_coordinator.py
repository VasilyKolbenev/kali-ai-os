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
    c.register("torch", torch.load, torch.probe)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    try:
        # ONE shared absolute deadline (0.1s) covers dep + model; the blocked
        # torch dep exhausts it → tts is a bounded TIMEOUT, its loader never runs.
        out = await asyncio.wait_for(c.ensure_ready("tts", timeout=0.1), timeout=2.0)  # watchdog
        assert out is ModelOutcome.TIMEOUT
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
        assert c.status("stt").state is ModelState.TIMEOUT  # observable TIMEOUT, worker alive
        assert await c.ensure_ready("stt", timeout=0.1) is ModelOutcome.TIMEOUT
        assert slow.calls == 1  # shared load — no 2nd loader
    finally:
        release.set()
        await asyncio.sleep(0.05)


# ── P1-1: probe-consistent completion ────────────────────────────────────────

async def test_loader_completes_but_probe_false_is_failed() -> None:
    # A loader that returns normally without flipping the engine-truth probe
    # (VAD swallowing a torch.hub failure) is FAILED, not READY.
    calls = {"n": 0}

    def _swallowed_load() -> None:
        calls["n"] += 1  # returns without loading

    c = ModelCoordinator(default_timeout=5.0)
    c.register("vad", _swallowed_load, lambda: False, voice_component=True)
    assert await c.ensure_ready("vad") is ModelOutcome.FAILED
    st = c.status("vad")
    assert st.state is ModelState.FAILED
    assert st.error == "loader_completed_probe_false"
    assert c.snapshot()["voice"] == "degraded"


async def test_late_probe_true_recovers_after_probe_false() -> None:
    # After a loader-completed-probe-false FAILED, a later true probe recovers to
    # READY with NO second loader (P1-1.5).
    state = {"loaded": False, "calls": 0}

    def _load() -> None:
        state["calls"] += 1  # returns without loading

    c = ModelCoordinator(default_timeout=5.0)
    c.register("stt", _load, lambda: state["loaded"], voice_component=True)
    assert await c.ensure_ready("stt") is ModelOutcome.FAILED
    state["loaded"] = True  # engine truth flips later
    assert c.status("stt").state is ModelState.READY
    assert await c.ensure_ready("stt") is ModelOutcome.READY
    assert state["calls"] == 1


# ── P1-2: single absolute deadline + observable TIMEOUT ───────────────────────

async def test_shared_deadline_dep_plus_model_times_out_within_budget() -> None:
    # dep 80ms + model 80ms under a single 100ms deadline → TIMEOUT within the
    # shared budget (NOT 160ms — the budget is not reset per stage).
    torch = FakeModel(delay=0.08)
    tts = FakeModel(delay=0.08)
    c = ModelCoordinator(default_timeout=5.0)
    c.register("torch", torch.load, torch.probe)
    c.register("tts", tts.load, tts.probe, deps=("torch",), voice_component=True)
    t0 = time.monotonic()
    out = await asyncio.wait_for(c.ensure_ready("tts", timeout=0.1), timeout=3.0)  # watchdog
    elapsed = time.monotonic() - t0
    # Primary discriminator: with a SHARED budget the dep (80ms) + the model wait
    # cannot both fit in 100ms → TIMEOUT. With a reset budget the model would get a
    # fresh full timeout and reach READY. `elapsed` is a loose sanity bound (well
    # below the model's 5s default) tolerant of scheduling jitter under load.
    assert out is ModelOutcome.TIMEOUT
    assert elapsed < 1.0, f"took {elapsed:.3f}s (model waited its full timeout → budget not shared)"
    # (whether the dep or the model wait exhausts the shared budget first is a
    # race; both are a bounded not-ready result. Observable TIMEOUT *status* for a
    # model's own wait is pinned by test_late_success_after_timeout_recovers.)


async def test_expired_deadline_starts_no_loader() -> None:
    # P1: a deadline already past at the single-flight decision must NOT start a
    # new heavy loader → TIMEOUT, loader.calls == 0, observable TIMEOUT/degraded.
    fake = FakeModel(delay=1.0)
    c, _ = _coord(tts=fake)
    out = await c.ensure_ready("tts", deadline_at=time.monotonic() - 1.0)
    assert out is ModelOutcome.TIMEOUT
    assert fake.calls == 0  # no new heavy work started after the deadline
    assert c.status("tts").state is ModelState.TIMEOUT
    assert c.snapshot()["voice"] == "degraded"


async def test_others_not_started_once_shared_deadline_exhausted() -> None:
    # P1.5 (no hidden warm-through): once the shared operation deadline is
    # exhausted (as if the first component consumed it), the remaining components
    # start NO loader. Deterministic: the shared deadline is already in the past
    # (no boundary race), exactly what the later components see in ensure_all_ready.
    others = {n: FakeModel(delay=1.0) for n in ("wake", "stt", "tts")}
    c = ModelCoordinator(default_timeout=5.0)
    for n, f in others.items():
        c.register(n, f.load, f.probe, voice_component=True)
    exhausted = time.monotonic() - 0.001  # the shared deadline already passed
    outs = {n: await c.ensure_ready(n, deadline_at=exhausted) for n in others}
    for n, f in others.items():
        assert outs[n] is ModelOutcome.TIMEOUT
        assert f.calls == 0, f"{n} started a loader after the deadline"
        assert c.status(n).state is ModelState.TIMEOUT
    assert c.snapshot()["voice"] == "degraded"


async def test_expired_deadline_preserves_terminal_error_not_masked_as_timeout() -> None:
    # P1 (terminal-error preservation): a deadline-denied retry must NOT clear an
    # existing terminal error nor relabel FAILED→TIMEOUT — that would MASK a real
    # failure. A pre-existing loader error is preserved byte-for-byte and surfaces
    # as FAILED; only a fresh (non-expired) retry that actually starts a loader
    # clears it. Mutation-sensitive: revert the deny branch to an unconditional
    # `m.error = None` and this test goes RED (step 2 sees TIMEOUT / error wiped).
    fake = FakeModel(fail=RuntimeError("corrupt weights"))
    c, _ = _coord(tts=fake)

    # 1) first load fails → FAILED with the original error
    assert await c.ensure_ready("tts") is ModelOutcome.FAILED
    assert await _poll(lambda: c.status("tts").state is ModelState.FAILED)
    assert c.status("tts").error == "RuntimeError: corrupt weights"
    assert fake.calls == 1

    # 2) deadline-denied retry → error PRESERVED byte-for-byte, still FAILED, no loader
    out = await c.ensure_ready("tts", deadline_at=time.monotonic() - 1.0)
    assert out is ModelOutcome.FAILED, "deadline-denial masked a terminal failure as TIMEOUT"
    assert c.status("tts").state is ModelState.FAILED
    assert c.status("tts").error == "RuntimeError: corrupt weights"
    assert fake.calls == 1  # no new heavy loader started past the deadline

    # 3) fresh non-expired retry → clears the error ON loader start, exactly one new load
    fake.fail = None
    assert await c.ensure_ready("tts", timeout=5.0) is ModelOutcome.READY
    assert fake.calls == 2
    assert c.status("tts").state is ModelState.READY


async def test_expired_deadline_clean_model_is_timeout_error_none() -> None:
    # Companion to the preservation test: an otherwise-clean (never-errored) model
    # denied at an expired deadline is an honest TIMEOUT with error=None and no
    # loader — the deny path only preserves a REAL prior error, it never invents one.
    fake = FakeModel(delay=1.0)
    c, _ = _coord(tts=fake)
    out = await c.ensure_ready("tts", deadline_at=time.monotonic() - 1.0)
    assert out is ModelOutcome.TIMEOUT
    assert fake.calls == 0
    st = c.status("tts")
    assert st.state is ModelState.TIMEOUT
    assert st.error is None


async def test_fresh_deadline_starts_each_loader_exactly_once() -> None:
    # P1.4: a fresh call with a new (non-expired) deadline clears TIMEOUT and
    # starts exactly one loader per still-needed component.
    models = {n: FakeModel(delay=0.02) for n in ("vad", "wake", "stt", "tts")}
    c = ModelCoordinator(default_timeout=5.0)
    for n, f in models.items():
        c.register(n, f.load, f.probe, voice_component=True)
    await c.ensure_all_ready(["vad", "wake", "stt", "tts"], timeout=0.001)  # expires → mostly denied
    outs = await c.ensure_all_ready(["vad", "wake", "stt", "tts"], timeout=5.0)  # fresh, generous
    assert all(o is ModelOutcome.READY for o in outs.values())
    for n, f in models.items():
        assert f.calls == 1, f"{n} loaded {f.calls}x"
        assert c.status(n).state is ModelState.READY


async def test_concurrent_callers_at_deadline_boundary_single_flight() -> None:
    fake = FakeModel(delay=0.05)
    c, _ = _coord(tts=fake)
    dl = time.monotonic() + 0.02
    outs = await asyncio.gather(*(c.ensure_ready("tts", deadline_at=dl) for _ in range(10)))
    assert fake.calls <= 1  # at most ONE loader across the boundary
    assert all(o in (ModelOutcome.TIMEOUT, ModelOutcome.READY) for o in outs)


async def test_late_success_after_timeout_recovers_to_ready() -> None:
    release = threading.Event()
    state = {"loaded": False, "calls": 0}

    def _load() -> None:
        state["calls"] += 1
        release.wait(5.0)
        state["loaded"] = True

    c = ModelCoordinator(default_timeout=5.0)
    c.register("tts", _load, lambda: state["loaded"], voice_component=True)
    try:
        assert await c.ensure_ready("tts", timeout=0.1) is ModelOutcome.TIMEOUT
        assert c.status("tts").state is ModelState.TIMEOUT
        release.set()  # worker completes late
        assert await _poll(lambda: c.status("tts").state is ModelState.READY, 3.0)
        assert await c.ensure_ready("tts") is ModelOutcome.READY
        assert state["calls"] == 1  # no 2nd loader
    finally:
        release.set()
        await asyncio.sleep(0.02)


async def test_timed_out_flag_reset_on_retry_so_status_not_stale_timeout() -> None:
    # Integrated-review finding: m.timed_out must clear when a fresh load starts,
    # else a healthy RETRY load (after a timeout + late failure) is mislabelled
    # TIMEOUT / voice=degraded while it is actually loading fine.
    release = threading.Event()
    state = {"calls": 0}

    def _load() -> None:
        state["calls"] += 1
        if state["calls"] == 1:
            time.sleep(0.15)  # first attempt: overruns the 0.05 wait, then fails
            raise RuntimeError("late fail")
        release.wait(5.0)  # retry attempt: stays loading (worker alive)

    c = ModelCoordinator(default_timeout=5.0)
    c.register("tts", _load, lambda: False, voice_component=True)
    try:
        assert await c.ensure_ready("tts", timeout=0.05) is ModelOutcome.TIMEOUT
        assert c.status("tts").state is ModelState.TIMEOUT  # live wait-timeout
        assert await _poll(lambda: c.status("tts").state is ModelState.FAILED, 2.0)  # load 1 failed

        assert await c.ensure("tts") is ModelOutcome.LOADING  # kick the retry (load 2)
        await asyncio.sleep(0.03)
        assert c.status("tts").state is ModelState.LOADING  # NOT a stale TIMEOUT
        assert c.snapshot()["voice"] == "loading"  # not 'degraded'
    finally:
        release.set()
        await asyncio.sleep(0.02)


async def test_concurrent_callers_different_deadlines_single_flight() -> None:
    fake = FakeModel(delay=0.1)
    c, _ = _coord(tts=fake)
    outs = await asyncio.gather(
        c.ensure_ready("tts", timeout=0.02),  # impatient → TIMEOUT
        c.ensure_ready("tts", timeout=5.0),   # patient → READY
    )
    assert fake.calls == 1  # single-flight across different deadlines
    assert ModelOutcome.READY in outs
    assert all(o in (ModelOutcome.READY, ModelOutcome.TIMEOUT) for o in outs)


async def test_ensure_all_ready_shares_one_operation_deadline() -> None:
    models = {n: FakeModel(delay=0.2) for n in ("vad", "wake", "stt", "tts")}
    c = ModelCoordinator(default_timeout=5.0)
    for n, f in models.items():
        c.register(n, f.load, f.probe, voice_component=True)
    t0 = time.monotonic()
    outs = await c.ensure_all_ready(["vad", "wake", "stt", "tts"], timeout=0.1)
    elapsed = time.monotonic() - t0
    # ONE 0.1s operation deadline, NOT 4×0.2s sequential.
    assert elapsed < 0.3, f"took {elapsed:.3f}s (per-model timeout, not shared)"
    assert any(o is ModelOutcome.TIMEOUT for o in outs.values())


async def test_stale_finalize_does_not_clobber_current_load() -> None:
    # Integrated-review finding (single-flight on the FAILURE path): a superseded
    # load's finalize (its future is no longer the model's current load_future —
    # e.g. a failed load whose retry has already started) MUST NOT null the live
    # retry's thread ref or set FAILED. Deterministic: drive the states directly.
    c = ModelCoordinator()
    fake = FakeModel()
    c.register("tts", fake.load, fake.probe)
    m = c._models["tts"]
    loop = asyncio.get_running_loop()

    fut_old = loop.create_future()
    fut_new = loop.create_future()
    sentinel_thread = threading.Thread(target=lambda: time.sleep(0.2), daemon=True)
    sentinel_thread.start()
    m.load_future = fut_new  # a retry is now the current load
    m.thread = sentinel_thread
    m.error = None

    fut_old.set_exception(RuntimeError("old load failed"))
    c._finalize(m, fut_old)  # stale finalize for the SUPERSEDED old load

    assert m.thread is sentinel_thread  # not clobbered
    assert m.error is None  # not marked FAILED by the stale load
    fut_new.cancel()  # cleanup
    sentinel_thread.join(timeout=1.0)


async def test_finalize_records_terminal_state_for_current_load() -> None:
    # The non-superseded finalize DOES record state (so the guard didn't over-shoot).
    c = ModelCoordinator()
    fake = FakeModel(fail=RuntimeError("boom"))
    c.register("tts", fake.load, fake.probe)
    assert await c.ensure_ready("tts") is ModelOutcome.FAILED
    assert await _poll(lambda: c.status("tts").state is ModelState.FAILED)


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
