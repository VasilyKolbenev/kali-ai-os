"""SandboxBackend protocol — pluggable execution backends.

Current implementation is `InProcessSandbox` (same-process, AST-gated).
Future implementations will swap in without changing callers:

- **DockerSandbox** — each skill in its own container (isolation, cross-platform)
- **CubeSandbox** — Tencent CubeVM (production multi-tenant on Linux servers)
- **E2BSandbox** — E2B cloud (KALI Cloud Phase 10)

Design principles:
1. Abstract over execution, not over discovery. Discovery stays in
   kernel/skills/registry.py (same everywhere).
2. Return structured results — no raw exceptions to callers.
3. Support pre-execution hooks (permission, rate limit, audit).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from kernel.action_preview import describe_action

logger = logging.getLogger(__name__)


@dataclass
class DispatchRequest:
    """A request to execute an action on an agent/skill."""

    agent_name: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    caller: str = "user"          # "user" | "llm" | "schedule" | "agent"
    request_id: str = ""


@dataclass
class DispatchResult:
    """The outcome of a dispatch attempt."""

    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
    denied_reason: str | None = None    # "permission" | "rate_limit" | "safety"
    backend: str = "unknown"            # implementation identifier


@runtime_checkable
class SandboxBackend(Protocol):
    """Contract every sandbox implementation must satisfy."""

    @property
    def name(self) -> str:
        """Stable identifier for telemetry/logging (e.g. "in_process")."""
        ...

    async def dispatch(self, req: DispatchRequest) -> DispatchResult:
        """Execute an action with all sandbox checks applied.

        Implementations MUST:
        - Run permission check (via injected enforcer) before execution
        - Run rate limit check (via injected limiter) before execution
        - Measure execution time and populate duration_ms
        - Translate raw exceptions into DispatchResult(ok=False, error=...)
        """
        ...

    async def health(self) -> dict[str, Any]:
        """Backend-specific health info (for /health/sandbox endpoint)."""
        ...


class InProcessSandbox:
    """Default backend — runs agent actions in the kernel process.

    Relies on:
    - kernel.builder.safety_gate (install-time AST check)
    - kernel.sandbox.permission_enforcer (dispatch-time capability check)
    - kernel.sandbox.rate_limiter (dispatch-time throttling)

    Not an isolation boundary against malicious code — a productivity layer
    for trusted/reviewed skills. Heavy-isolation use cases should use
    DockerSandbox (desktop) or CubeSandbox (server) when implemented.
    """

    name = "in_process"

    def __init__(
        self,
        *,
        agent_runtime: Any,
        enforcer: Any = None,
        rate_limiter: Any = None,
        audit_sink: Any = None,
    ) -> None:
        """Wire the backend with its dependencies.

        Args:
            agent_runtime: Any object with `async dispatch(name, action, args)`.
            enforcer: PermissionEnforcer-like with `can_execute(agent, method)`.
            rate_limiter: RateLimiter-like with `check(agent)` returning bool.
            audit_sink: Optional callable taking a dict record.
        """
        self._runtime = agent_runtime
        self._enforcer = enforcer
        self._rate_limiter = rate_limiter
        self._audit_sink = audit_sink

    async def dispatch(self, req: DispatchRequest) -> DispatchResult:
        start = time.perf_counter()
        record: dict[str, Any] = {
            "timestamp": time.time(),
            "backend": self.name,
            "agent": req.agent_name,
            "action": req.action,
            "caller": req.caller,
            "request_id": req.request_id,
            "status": "pending",
        }
        # Dry-run preview v1 (disclosure-only): attach a plain-language label +
        # risk tier so the Activity view shows, in plain Russian, what the action
        # does. Non-gating — does not change execution.
        preview = describe_action(req.agent_name, req.action, req.args)
        record["preview_label"] = preview["label"]
        record["preview_risk"] = preview["risk"]

        try:
            # --- Rate limit ------------------------------------------------
            if self._rate_limiter is not None:
                if not self._rate_limiter.check(req.agent_name):
                    record.update(status="denied", denied_reason="rate_limit")
                    self._emit_audit(record)
                    return DispatchResult(
                        ok=False,
                        error="Rate limit exceeded",
                        denied_reason="rate_limit",
                        backend=self.name,
                        duration_ms=int((time.perf_counter() - start) * 1000),
                    )

            # --- Permission check ------------------------------------------
            if self._enforcer is not None:
                rpc_method = f"execute:{req.action}"
                if not self._enforcer.can_execute(req.agent_name, rpc_method):
                    # Fall through only if enforcer is wired with this agent
                    # and denies. Unknown agents pass (discovery-friendly) —
                    # but PermissionEnforcer.can_execute returns False for
                    # unregistered agents. That's strict mode; we want to
                    # allow dispatch to unregistered agents (they may be
                    # auto-approved built-ins).
                    has_registration = req.agent_name in getattr(
                        self._enforcer, "_permissions", {},
                    )
                    if has_registration:
                        record.update(status="denied", denied_reason="permission")
                        self._emit_audit(record)
                        return DispatchResult(
                            ok=False,
                            error=f"Agent '{req.agent_name}' not authorized for '{req.action}'",
                            denied_reason="permission",
                            backend=self.name,
                            duration_ms=int((time.perf_counter() - start) * 1000),
                        )

            # --- Execute ---------------------------------------------------
            try:
                result = await self._runtime.dispatch(
                    req.agent_name, req.action, req.args,
                )
            except Exception as exc:
                logger.exception(
                    "In-process dispatch failed: agent=%s action=%s",
                    req.agent_name, req.action,
                )
                record.update(status="error", error=str(exc))
                self._emit_audit(record)
                return DispatchResult(
                    ok=False,
                    error=str(exc),
                    backend=self.name,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )

            duration_ms = int((time.perf_counter() - start) * 1000)
            record.update(status="ok", duration_ms=duration_ms)
            self._emit_audit(record)
            return DispatchResult(
                ok=True,
                result=result if isinstance(result, dict) else {"result": result},
                duration_ms=duration_ms,
                backend=self.name,
            )
        except Exception as exc:  # defensive — should never reach here
            logger.exception("Unexpected sandbox error")
            record.update(status="error", error=f"sandbox: {exc}")
            self._emit_audit(record)
            return DispatchResult(
                ok=False,
                error=f"Sandbox error: {exc}",
                backend=self.name,
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

    async def health(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "enforcer_enabled": self._enforcer is not None,
            "rate_limiter_enabled": self._rate_limiter is not None,
            "audit_sink_enabled": self._audit_sink is not None,
        }

    def _emit_audit(self, record: dict[str, Any]) -> None:
        """Dispatch a copy of the record to the audit sink (if configured)."""
        if self._audit_sink is None:
            return
        try:
            self._audit_sink(dict(record))
        except Exception:
            logger.exception("Audit sink failed")
