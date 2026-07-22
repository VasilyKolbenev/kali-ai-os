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
    # Shared single-flight completion: the daemon future of the CURRENT load.
    # Concurrent callers AWAIT this same future (bounded) — one loader, one
    # completion — instead of racing on a transient LOADING flag.
    load_future: asyncio.Future | None = None


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
            return ModelStatus(ModelState.LOADING)  # worker running (incl. a wait-timed-out load)
        if m.error is not None:
            return ModelStatus(ModelState.FAILED, m.error)
        if m.disabled:
            return ModelStatus(ModelState.DISABLED)
        return ModelStatus(ModelState.NOT_STARTED)

    def _finalize(self, m: _Model, fut: asyncio.Future) -> None:
        """Done-callback for a load's daemon future: record terminal state once."""
        if fut.cancelled():
            m.thread = None
            return
        exc = fut.exception()
        m.thread = None
        if exc is None:
            m.ready_at = time.perf_counter()
            dur = int((m.ready_at - m.started_at) * 1000) if m.started_at else None
            self._emit(m.name, "ready", dur)
        else:
            m.error = f"{type(exc).__name__}: {exc}"
            self._emit(m.name, "failed")

    async def _acquire_load(self, m: _Model) -> asyncio.Future | None:
        """Return the SHARED in-flight load future (starting one if needed), or
        ``None`` if already loaded. Never starts a 2nd loader while a worker is
        alive — the single-flight point (called under the model lock)."""
        async with m.lock:
            if _safe_probe(m):
                return None
            if m.thread is not None and m.thread.is_alive():
                return m.load_future  # in-flight — share the same completion
            m.error = None
            m.started_at = time.perf_counter()
            self._emit(m.name, "loading")
            fut, t = _run_in_daemon(m.loader)
            m.thread = t
            m.load_future = fut
            fut.add_done_callback(lambda f: self._finalize(m, f))
            return fut

    async def _resolve_deps(self, m: _Model, *, timeout: float | None = None) -> bool:
        """Wait each dependency to READY with an absolute per-dep deadline (bounded).
        On TIMEOUT/FAILED/DISABLED the dependent is NOT started (no bypass, no hang)."""
        for dep in m.deps:
            d = self._models[dep]
            deadline = timeout if timeout is not None else d.timeout
            out = await self.ensure_ready(dep, timeout=deadline)
            if out is not ModelOutcome.READY:
                m.error = f"dependency {dep!r} not ready: {out.value}"
                return False
        return True

    async def ensure(self, name: str) -> ModelOutcome:
        """Fail-fast on-demand kick: DISABLED/READY fast; deps waited (bounded);
        then start the load in the BACKGROUND and return LOADING without waiting
        for it (used by prewarm). Never starts a 2nd loader."""
        m = self._models[name]
        if m.disabled:
            return ModelOutcome.DISABLED
        if _safe_probe(m):
            return ModelOutcome.READY
        if not await self._resolve_deps(m):
            return ModelOutcome.FAILED
        fut = await self._acquire_load(m)
        return ModelOutcome.READY if fut is None else ModelOutcome.LOADING

    async def ensure_ready(self, name: str, *, timeout: float | None = None) -> ModelOutcome:
        """WAITING API: join the shared single-flight completion and wait — BOUNDED
        by an absolute deadline — until READY/FAILED/TIMEOUT/DISABLED. Never starts
        a 2nd loader; never hangs. Used by auto-start, /voice/start, dependency
        resolution and the fail-closed HTTP routes."""
        m = self._models[name]
        if m.disabled:
            return ModelOutcome.DISABLED
        if _safe_probe(m):
            return ModelOutcome.READY
        if not await self._resolve_deps(m, timeout=timeout):
            return ModelOutcome.FAILED
        fut = await self._acquire_load(m)
        if fut is None:
            return ModelOutcome.READY
        deadline = timeout if timeout is not None else m.timeout
        try:
            await asyncio.wait_for(asyncio.shield(fut), deadline)
            return ModelOutcome.READY
        except asyncio.TimeoutError:
            return ModelOutcome.TIMEOUT  # worker still running; no 2nd loader
        except asyncio.CancelledError:
            raise
        except Exception:
            return ModelOutcome.FAILED  # loader raised (offline/missing/corrupt)

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
