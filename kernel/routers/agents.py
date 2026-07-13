"""Agents endpoints (registry, runtime, consent, custom agents) — extracted
from kernel/main.py (T5).

Bodies are byte-identical to the pre-split closures (only ``@app.`` →
``@router.``); ``_get_sandbox`` comes from routers/_shared (app-parameterized).
Def order preserves main.py registration order (sacred).
"""
from __future__ import annotations

from datetime import UTC
from typing import Any

from fastapi import APIRouter, Request

from kernel.models import Event
from kernel.routers._shared import _get_sandbox

router = APIRouter()


@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, Any]]:
    return [a.model_dump() for a in request.app.state.plugin_registry.list_registered()]


@router.get("/agents/tools")
async def list_tools(request: Request) -> list[dict[str, Any]]:
    return request.app.state.plugin_registry.get_all_tools()


@router.get("/agents/{name}/capabilities")
async def agent_capabilities(name: str, request: Request) -> dict[str, Any]:
    """Plain-language capability disclosure for the consent-disclosure flow.

    Returns the agent's manifest capabilities classified into RU labels and
    risk tiers (see kernel.capabilities). Disclosure only — does not change
    any permission/enforcement behavior. Unknown agents return an empty,
    non-sensitive result (never 404) so the UI never crashes.
    """
    from kernel.capabilities import describe_capabilities

    manifest = request.app.state.plugin_registry.get(name)
    caps = manifest.capabilities if manifest else []
    return {"name": name, **describe_capabilities(caps)}


@router.get("/agents/running")
async def running_agents(request: Request) -> list[dict[str, Any]]:
    return request.app.state.agent_runtime.list_agents()


@router.get("/agents/config-status")
async def agents_config_status() -> dict[str, Any]:
    """Per-agent credential status so the UI can show «Нужна настройка».

    «running» means the process is up; this says whether the keys it needs
    are actually present — the difference between «Работает» and a button
    that does nothing.
    """
    from kernel.agent_keys import all_agents_config_status
    return all_agents_config_status()


async def _approve_agent(s: Any, name: str, *, explicit: bool = False) -> None:
    """Grant runtime permission to an agent the user enabled.

    Explicit user actions (enabling via «Включить» / «Разрешить») always
    approve and clear any prior revoke. Implicit approvals (a direct tool
    call) respect a STICKY revoke: a revoked agent stays unapproved until
    the user explicitly re-enables it — M2.2 semantics A. Consent is
    persisted so it (and a revoke) survives a restart.
    """
    from datetime import datetime

    manifest = s.plugin_registry.get(name)
    if not (manifest and s.permission_enforcer):
        return
    db = getattr(s, "database", None)
    if not explicit and db is not None and await db.get_consent(name) == "revoked":
        return  # sticky revoke — wait for an explicit re-enable
    manifest.permissions.user_approved = True
    manifest.permissions.approval_timestamp = datetime.now(UTC)
    s.permission_enforcer.register_agent(name, manifest)
    if db is not None:
        await db.set_consent(name, "approved")


@router.post("/agents/{name}/load")
async def load_agent(name: str, request: Request) -> dict[str, str]:
    try:
        s = request.app.state
        await s.agent_runtime.load_agent(name)
        await _approve_agent(s, name, explicit=True)
        return {"status": "loaded", "agent": name}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@router.post("/agents/{name}/unload")
async def unload_agent(name: str, request: Request) -> dict[str, str]:
    await request.app.state.agent_runtime.unload_agent(name)
    return {"status": "unloaded", "agent": name}


@router.post("/agents/{name}/revoke")
async def revoke_agent(name: str, request: Request) -> dict[str, str]:
    """Revoke a previously-granted consent (sticky — M2.2 semantics A).

    Clears approval in-memory (the enforcer shares the PermissionSet object,
    so calls are denied immediately) and persists the revoke so it survives
    a restart and is not undone by an implicit approve-on-execute.
    """
    s = request.app.state
    manifest = s.plugin_registry.get(name)
    if manifest:
        manifest.permissions.user_approved = False
    db = getattr(s, "database", None)
    if db is not None:
        await db.set_consent(name, "revoked")
    return {"status": "revoked", "agent": name}


@router.get("/agents/consents")
async def list_consents(request: Request) -> dict[str, str]:
    """Persisted per-agent consent state — ``{name: 'approved'|'revoked'}``.

    Lets the UI reflect durable consent (M2.2): which agents have a granted,
    revocable consent vs. which were revoked, so a revoke / re-enable control
    shows real state across reloads and restarts. Empty if never recorded.
    """
    db = getattr(request.app.state, "database", None)
    if db is None:
        return {}
    return await db.get_all_consents()


@router.get("/agents/{name}/status")
async def agent_status(name: str, request: Request) -> dict[str, Any]:
    return await request.app.state.agent_runtime.get_status(name)


@router.post("/agents/{name}/execute")
async def execute_agent_tool(name: str, request: Request) -> dict[str, Any]:
    """Execute an agent tool/action directly."""
    body = await request.json()
    action = body.get("action", "")
    args = body.get("args", {})

    runtime = request.app.state.agent_runtime

    try:
        status = await runtime.get_status(name)
    except Exception:
        status = None

    if not status or status.get("status") != "running":
        try:
            await runtime.load_agent(name)
        except Exception as e:
            return {"error": f"Agent '{name}' not available: {e}"}

    # A direct tool call implicitly approves a not-yet-revoked agent so an
    # already-running-but-unapproved agent doesn't 403. A sticky revoke
    # (M2.2) is respected: a revoked agent stays denied until re-enabled.
    await _approve_agent(request.app.state, name, explicit=False)

    # Route through SandboxBackend — adds permission + rate limit + audit
    sandbox = _get_sandbox(request.app)
    from kernel.sandbox.backend import DispatchRequest
    dispatch_result = await sandbox.dispatch(
        DispatchRequest(
            agent_name=name, action=action, args=args,
            caller=body.get("caller", "user"),
            request_id=body.get("request_id", ""),
        )
    )

    if dispatch_result.ok:
        # Unwrap the single-key "result" envelope for backward compat
        payload = dispatch_result.result or {}
        if set(payload.keys()) == {"result"}:
            payload = payload["result"] if isinstance(payload["result"], dict) else payload

        # Live Canvas: push widget updates to UI via EventBus → WebSocket
        if name == "live-canvas" and action in ("render_widget", "clear_canvas"):
            await request.app.state.event_bus.publish(
                Event(
                    topic="canvas.update",
                    source="live-canvas",
                    payload={"action": action, **payload},
                )
            )

        return payload

    # Map denial reason → HTTP status for API clients that care
    from fastapi.responses import JSONResponse
    http_status = 200
    if dispatch_result.denied_reason == "rate_limit":
        http_status = 429
    elif dispatch_result.denied_reason == "permission":
        http_status = 403

    return JSONResponse(
        {
            "error": dispatch_result.error or "dispatch failed",
            "denied_reason": dispatch_result.denied_reason,
            "agent": name,
            "action": action,
            "duration_ms": dispatch_result.duration_ms,
        },
        status_code=http_status,
    )


@router.post("/agents/create")
async def create_custom_agent(request: Request) -> dict[str, Any]:
    body = await request.json()
    template = body.get("template")
    if template:
        return request.app.state.agent_builder.create_from_template(
            body["name"], body.get("description", ""), template
        )
    return request.app.state.agent_builder.create_agent(
        name=body["name"],
        description=body.get("description", ""),
        tools=body.get("tools", []),
        action_code=body.get("code", ""),
        permissions=body.get("permissions"),
    )


@router.get("/agents/custom")
async def list_custom_agents(request: Request) -> list[dict[str, Any]]:
    return request.app.state.agent_builder.list_custom_agents()


@router.delete("/agents/custom/{name}")
async def delete_custom_agent(name: str, request: Request) -> dict[str, Any]:
    return request.app.state.agent_builder.delete_agent(name)
