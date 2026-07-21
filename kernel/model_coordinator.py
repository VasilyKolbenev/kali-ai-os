"""Single-flight, observable model loader for the voice stack (OPUS-102).

The coordinator moves heavy model loads OFF the critical FastAPI lifespan path:
`prewarm` spawns strong-referenced background tasks, and `ensure` is single-flight
so a background prewarm and the first on-demand request never double-load.

State is DERIVED from the engine's own truth via a `probe` (e.g.
``tts_router.is_loaded()``), not a cached flag — so a load triggered elsewhere
(pipeline auto-start, ``/voice/start``) is still reported READY instead of a
stale NOT_STARTED. The actual weight-load-once guarantee rests on the engines'
own locks (``tts_engine_f5._load_lock``, ``transcribe_helper._stt_lock``); the
coordinator's per-model :class:`asyncio.Lock` only dedups prewarm/ensure callers.

Honest shutdown: :meth:`shutdown` cancels and awaits the asyncio task wrappers.
A load already running inside a worker thread (``asyncio.to_thread``) cannot be
force-cancelled and runs to completion — the coordinator does not claim otherwise.
"""
from __future__ import annotations

import asyncio
import logging
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
    DISABLED = "disabled"  # inactive engine — prewarm suppressed (on-demand still loads)


@dataclass
class ModelStatus:
    """Immutable status snapshot for one model."""

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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    error: str | None = None
    started_at: float | None = None
    ready_at: float | None = None
    loading: bool = False


def _safe_probe(m: _Model) -> bool:
    try:
        return bool(m.probe())
    except Exception:  # a probe must never break status reporting
        return False


class ModelCoordinator:
    """Owns background prewarm + single-flight on-demand loads for voice models."""

    def __init__(self, event_bus: Any = None, *, default_timeout: float = DEFAULT_LOAD_TIMEOUT) -> None:
        self._models: dict[str, _Model] = {}
        self._bus = event_bus
        self._default_timeout = default_timeout
        self._tasks: set[asyncio.Task[None]] = set()

    def register(
        self,
        name: str,
        loader: Callable[[], Any],
        probe: Callable[[], bool],
        *,
        timeout: float | None = None,
        disabled: bool = False,
    ) -> None:
        """Register a model with a blocking ``loader`` and an engine-truth ``probe``.

        Args:
            name: Model id (e.g. ``"tts"``/``"stt"``).
            loader: Blocking callable that loads weights (run via ``to_thread``).
            probe: Returns True iff the engine already has the model loaded.
            timeout: Per-load timeout in seconds.
            disabled: If True, ``prewarm`` skips it (inactive engine); an explicit
                ``ensure`` still loads on demand.
        """
        self._models[name] = _Model(
            name=name,
            loader=loader,
            probe=probe,
            timeout=timeout or self._default_timeout,
            disabled=disabled,
        )

    def has(self, name: str) -> bool:
        """True iff ``name`` is registered."""
        return name in self._models

    def status(self, name: str) -> ModelStatus:
        """Return the current status, deriving READY from the engine-truth probe."""
        m = self._models[name]
        if _safe_probe(m):
            dur = (
                int((m.ready_at - m.started_at) * 1000)
                if m.ready_at is not None and m.started_at is not None
                else None
            )
            return ModelStatus(ModelState.READY, None, dur)
        if m.loading:
            return ModelStatus(ModelState.LOADING)
        if m.error is not None:
            return ModelStatus(ModelState.FAILED, m.error)
        if m.disabled:
            return ModelStatus(ModelState.DISABLED)
        return ModelStatus(ModelState.NOT_STARTED)

    async def ensure(self, name: str) -> None:
        """Single-flight load: no-op if already loaded, else load once under a lock.

        Never raises on load failure (records FAILED); callers check ``status`` and
        degrade. Propagates :class:`asyncio.CancelledError` for graceful shutdown.
        """
        m = self._models[name]
        if _safe_probe(m):
            return
        async with m.lock:
            if _safe_probe(m):
                return
            m.loading = True
            m.error = None
            m.started_at = time.perf_counter()
            self._emit(name, "loading")
            try:
                await asyncio.wait_for(asyncio.to_thread(m.loader), m.timeout)
                m.ready_at = time.perf_counter()
                dur = int((m.ready_at - m.started_at) * 1000)
                self._emit(name, "ready", dur)
            except asyncio.CancelledError:
                self._emit(name, "cancelled")
                logger.info("model %s load cancelled (shutdown)", name)
                raise
            except Exception as e:  # offline/missing/corrupt → degraded, never hang
                m.error = f"{type(e).__name__}: {e}"
                self._emit(name, "failed")
                logger.warning("model %s load failed: %s", name, m.error)
            finally:
                m.loading = False

    def prewarm(self, names: list[str]) -> None:
        """Spawn strong-referenced background loads for the active (non-disabled) models."""
        for name in names:
            m = self._models.get(name)
            if m is None or m.disabled:
                continue
            task = asyncio.create_task(self.ensure(name), name=f"prewarm:{name}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def inflight_count(self) -> int:
        """Number of not-yet-finished prewarm task wrappers (for shutdown assertions)."""
        return sum(1 for t in self._tasks if not t.done())

    async def shutdown(self) -> None:
        """Cancel and await all prewarm task wrappers.

        Honest guarantee: the asyncio wrappers are cancelled+awaited (no orphaned
        Task). A weight load already executing in a worker thread runs to
        completion; it is not force-killed.
        """
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
        """Machine-readable status for ``/ready`` and voice observability."""
        models = {
            name: {
                "state": st.state.value,
                "error": st.error,
                "duration_ms": st.duration_ms,
            }
            for name, st in ((n, self.status(n)) for n in self._models)
        }
        return {"models": models, "voice": self._voice_overall()}

    def _voice_overall(self) -> str:
        voice = [self.status(n).state for n in ("stt", "tts") if n in self._models]
        if not voice:
            return "idle"
        if any(s is ModelState.FAILED for s in voice):
            return "degraded"
        if any(s is ModelState.LOADING for s in voice):
            return "loading"
        if all(s is ModelState.READY for s in voice):
            return "ready"
        if all(s is ModelState.DISABLED for s in voice):
            return "disabled"
        return "idle"

    def _emit(self, name: str, state: str, duration_ms: int | None = None) -> None:
        """Structured milestone line; the machine-readable API is :meth:`snapshot`."""
        if duration_ms is not None:
            logger.info("milestone model.%s.%s duration_ms=%d", name, state, duration_ms)
        else:
            logger.info("milestone model.%s.%s", name, state)
