"""Single-flight, observable model loader for the voice stack (OPUS-102).

Heavy loads run OFF the critical FastAPI lifespan path: `prewarm` spawns
strong-referenced background tasks and `ensure` is single-flight so a background
prewarm and the first on-demand request never double-load.

Loaders run in **daemon** threads (not `asyncio.to_thread`, whose default
executor is joined at interpreter exit) so a blocked loader can never hold the
process past the shutdown SLA — the interpreter abandons daemon threads. This is
graceful (no `os._exit`); a load already running is simply not force-stopped.

Dependencies (`deps`) load first and to completion, enforced inside `ensure`
with no bypass — the `torch` model is a dep of every voice model so the frozen
`_MEIPASS` "import torch once, on a worker thread, before any model" guarantee is
preserved without blocking startup.

State is DERIVED from the engine's own truth via a `probe`; the weight-load-once
guarantee rests on the engines' own locks. A timed-out load whose worker thread
is still alive reports LOADING and never starts a second loader.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("kernel.model_coordinator")

DEFAULT_LOAD_TIMEOUT = 180.0


class ModelState(str, Enum):
    """User-facing load state for a single model."""

    NOT_STARTED = "not_started"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DISABLED = "disabled"  # inactive engine — prewarm suppressed


class ModelOutcome(str, Enum):
    """Typed result of an `ensure` call."""

    READY = "ready"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DISABLED = "disabled"
    LOADING = "loading"  # a prior (possibly timed-out) load is still in-flight


class ModelUnavailable(Exception):
    """Raised by route helpers when a required model is not READY."""

    def __init__(self, name: str, outcome: ModelOutcome, error: str | None = None) -> None:
        self.name = name
        self.outcome = outcome
        self.error = error
        super().__init__(f"model {name!r} unavailable: {outcome.value}")


@dataclass
class ModelStatus:
    state: ModelState
    error: str | None = None
    duration_ms: int | None = None


@dataclass
class _Model:
    name: str
    loader: Callable[[], Any]
    probe: Callable[[], bool]
    timeout: float
    disabled: bool = False
    deps: tuple[str, ...] = ()
    voice_component: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    error: str | None = None
    started_at: float | None = None
    ready_at: float | None = None
    thread: threading.Thread | None = None


def _safe_probe(m: _Model) -> bool:
    try:
        return bool(m.probe())
    except Exception:
        return False


def _run_in_daemon(fn: Callable[[], Any]) -> tuple[asyncio.Future, threading.Thread]:
    """Run ``fn`` in a daemon thread; bridge the result to an asyncio Future.

    Daemon so the interpreter never joins it at exit (bounded shutdown). The
    completion marshal is guarded against a closed loop (shutdown TOCTOU).
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _settle(setter: Callable[[Any], None], value: Any) -> None:
        if not fut.done():
            setter(value)

    def _worker() -> None:
        try:
            result = fn()
            err: BaseException | None = None
        except BaseException as e:  # noqa: BLE001 — marshal every failure to the awaiter
            result, err = None, e
        try:
            if err is None:
                loop.call_soon_threadsafe(_settle, fut.set_result, result)
            else:
                loop.call_soon_threadsafe(_settle, fut.set_exception, err)
        except RuntimeError:
            pass  # event loop already closed at shutdown — nothing awaits the Future

    t = threading.Thread(target=_worker, daemon=True, name="kali-model-load")
    t.start()
    return fut, t


class ModelCoordinator:
    """Owns background prewarm + single-flight on-demand loads for voice models."""

    def __init__(self, event_bus: Any = None, *, default_timeout: float = DEFAULT_LOAD_TIMEOUT) -> None:
        self._models: dict[str, _Model] = {}
        self._bus = event_bus
        self._default_timeout = default_timeout
        self._tasks: set[asyncio.Task[Any]] = set()

    def register(
        self,
        name: str,
        loader: Callable[[], Any],
        probe: Callable[[], bool],
        *,
        timeout: float | None = None,
        disabled: bool = False,
        deps: tuple[str, ...] = (),
        voice_component: bool = False,
    ) -> None:
        """Register a model with a blocking ``loader`` and an engine-truth ``probe``.

        ``deps`` (e.g. ``("torch",)``) load to completion before this model; a
        model may not depend on itself. ``voice_component`` marks VAD/wake/STT/TTS
        for the aggregate voice state.
        """
        if name in deps:
            raise ValueError(f"model {name!r} cannot depend on itself")
        self._models[name] = _Model(
            name=name,
            loader=loader,
            probe=probe,
            timeout=timeout or self._default_timeout,
            disabled=disabled,
            deps=deps,
            voice_component=voice_component,
        )

    def has(self, name: str) -> bool:
        return name in self._models

    def is_disabled(self, name: str) -> bool:
        m = self._models.get(name)
        return bool(m and m.disabled)

    def status(self, name: str) -> ModelStatus:
        """Status derived from the engine-truth probe / live worker thread."""
        m = self._models[name]
        if _safe_probe(m):
            dur = (
                int((m.ready_at - m.started_at) * 1000)
                if m.ready_at is not None and m.started_at is not None
                else None
            )
            return ModelStatus(ModelState.READY, None, dur)
        if m.thread is not None and m.thread.is_alive():
            return ModelStatus(ModelState.LOADING)
        if m.error is not None:
            state = ModelState.TIMEOUT if "timeout" in m.error else ModelState.FAILED
            return ModelStatus(state, m.error)
        if m.disabled:
            return ModelStatus(ModelState.DISABLED)
        return ModelStatus(ModelState.NOT_STARTED)

    async def ensure(self, name: str) -> ModelOutcome:
        """Single-flight load; returns a typed outcome (never raises on load failure).

        Fast-paths DISABLED / already-READY / in-flight-LOADING before the lock so
        a caller never blocks behind a slow load. Loads ``deps`` to completion
        first (no bypass). Propagates :class:`asyncio.CancelledError`.
        """
        m = self._models[name]
        if m.disabled:
            return ModelOutcome.DISABLED
        if _safe_probe(m):
            return ModelOutcome.READY
        # A prior load (incl. a timed-out one whose worker is still running) is
        # in flight → do not wait on the lock, do not start a 2nd loader.
        if m.thread is not None and m.thread.is_alive():
            return ModelOutcome.LOADING

        for dep in m.deps:
            out = await self.ensure(dep)
            if out is not ModelOutcome.READY:
                m.error = f"dependency {dep!r} not ready: {out.value}"
                return ModelOutcome.FAILED

        async with m.lock:
            if _safe_probe(m):
                return ModelOutcome.READY
            if m.thread is not None and m.thread.is_alive():
                return ModelOutcome.LOADING
            m.error = None
            m.started_at = time.perf_counter()
            self._emit(name, "loading")
            fut, t = _run_in_daemon(m.loader)
            m.thread = t
            try:
                await asyncio.wait_for(asyncio.shield(fut), m.timeout)
            except asyncio.CancelledError:
                self._emit(name, "cancelled")
                raise
            except asyncio.TimeoutError:
                # Worker still running (daemon) → keep m.thread so status reports
                # LOADING and no 2nd loader starts until it dies or the probe flips.
                m.error = f"timeout after {m.timeout:.0f}s"
                self._emit(name, "timeout")
                return ModelOutcome.TIMEOUT
            except Exception as e:  # offline/missing/corrupt → degraded, never hang
                # Concluded (failed): drop the thread ref so status doesn't race on
                # the daemon thread's not-yet-observed exit and misreport LOADING.
                m.thread = None
                m.error = f"{type(e).__name__}: {e}"
                self._emit(name, "failed")
                return ModelOutcome.FAILED
            m.thread = None
            m.ready_at = time.perf_counter()
            self._emit(name, "ready", int((m.ready_at - m.started_at) * 1000))
            return ModelOutcome.READY

    async def run_blocking(self, fn: Callable[[], Any], *, timeout: float | None = None) -> Any:
        """Run a blocking callable (e.g. a warmup synth) in a daemon thread so it
        never holds the process past shutdown. Cancellation abandons the thread."""
        fut, _t = _run_in_daemon(fn)
        if timeout is not None:
            return await asyncio.wait_for(asyncio.shield(fut), timeout)
        return await asyncio.shield(fut)

    def prewarm(self, names: list[str]) -> None:
        """Spawn strong-referenced background loads for active (non-disabled) models."""
        for name in names:
            m = self._models.get(name)
            if m is None or m.disabled:
                continue
            task = asyncio.create_task(self.ensure(name), name=f"prewarm:{name}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def inflight_count(self) -> int:
        return sum(1 for t in self._tasks if not t.done())

    async def shutdown(self) -> None:
        """Cancel + await the asyncio task wrappers. Daemon loader threads are
        abandoned (interpreter reclaims them at exit) — the process is not held."""
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    def snapshot(self) -> dict[str, Any]:
        models = {
            name: {"state": st.state.value, "error": st.error, "duration_ms": st.duration_ms}
            for name, st in ((n, self.status(n)) for n in self._models)
        }
        return {"models": models, "voice": self._voice_overall()}

    def _voice_overall(self) -> str:
        voice = [self.status(n).state for n, m in self._models.items() if m.voice_component]
        if not voice:
            return "idle"
        if all(s is ModelState.DISABLED for s in voice):
            return "disabled"
        if any(s in (ModelState.FAILED, ModelState.TIMEOUT) for s in voice):
            return "degraded"
        if any(s is ModelState.LOADING for s in voice):
            return "loading"
        if all(s is ModelState.READY for s in voice):
            return "ready"
        return "loading"

    def _emit(self, name: str, state: str, duration_ms: int | None = None) -> None:
        if duration_ms is not None:
            logger.info("milestone model.%s.%s duration_ms=%d", name, state, duration_ms)
        else:
            logger.info("milestone model.%s.%s", name, state)
