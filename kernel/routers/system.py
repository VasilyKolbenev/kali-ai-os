"""System endpoints (health, config, settings, llm test, sandbox inspection)
— extracted from kernel/main.py (T7).

Bodies are byte-identical to the pre-split closures (only ``@app.`` →
``@router.``); ``_get_sandbox``/``_mask_key``/``_save_env`` come from
routers/_shared. ``/health/tts`` lives in routers/voice.py (its main.py def
order was inside the voice block). Def order preserves main.py registration
order (sacred). ``_GUARDED_SECTIONS`` stays inside the patch_config body.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request

from kernel import __version__
from kernel.config_manager import ConfigManager
from kernel.models import ConfigSchema, Event
from kernel.routers._shared import _get_sandbox, _mask_key, _save_env

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    s = request.app.state
    # desktop_instance_id: per-spawn ID проброшенный desktop-shell через env
    # (ownership-контракт A3/OPUS-101). При ручном запуске без env — null, тогда
    # HealthProbe десктопа трактует backend как ForeignHealthy (не наш).
    return {
        "status": "ok",
        "version": __version__,
        "desktop_instance_id": os.environ.get("KALI_DESKTOP_INSTANCE_ID"),
        "components": {
            "event_bus": {"subscribers": s.event_bus.subscriber_count},
            "database": {"connected": s.database.is_connected},
            "scheduler": s.scheduler.get_schedule_info(),
        },
    }


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    return request.app.state.config_manager.config.model_dump()


@router.patch("/config")
async def patch_config(request: Request):
    """Apply an RFC 7396 JSON Merge Patch to the YAML config.

    Semantics:
      - Body is merged into the current config via merge_patch().
      - A `null` value at a known top-level section (voice, llm, schedule,
        server) is rejected with 422 — this path exists only to guard
        against accidental wipes; use an explicit reset endpoint if that
        becomes a real need.
      - The merged result is validated against ConfigSchema. On failure the
        client receives 422 and the on-disk file is NOT modified.
      - On success the file is saved atomically (tempfile + os.replace)
        with a `.bak` sibling containing the prior contents.
      - After write the config is reloaded and `config.changed` is
        published on the event bus so live subscribers can react.
    """
    from fastapi.responses import JSONResponse
    from pydantic import ValidationError

    from kernel.config_manager import merge_patch

    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse({"error": f"invalid JSON: {exc}"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "request body must be a JSON object"},
            status_code=400,
        )

    _GUARDED_SECTIONS = {"voice", "llm", "schedule", "server"}
    nulled = [k for k in _GUARDED_SECTIONS if k in body and body[k] is None]
    if nulled:
        return JSONResponse(
            {
                "error": "cannot null a top-level section via PATCH",
                "sections": nulled,
            },
            status_code=422,
        )

    cm: ConfigManager = request.app.state.config_manager
    current = cm.config.model_dump()
    merged = merge_patch(current, body)

    try:
        validated = ConfigSchema.model_validate(merged)
    except ValidationError as exc:
        return JSONResponse(
            {"error": "invalid config", "detail": exc.errors()},
            status_code=422,
        )

    saved = cm.save(validated)

    await request.app.state.event_bus.publish(
        Event(
            topic="config.changed",
            source="kernel",
            payload={"sections": sorted(body.keys())},
        )
    )

    return saved.model_dump()


@router.post("/llm/test")
async def llm_test(request: Request) -> dict[str, Any]:
    """Live validation of an API key for a provider.

    Makes one minimal request to the provider's chat endpoint. Returns
    {ok: True} on success, {ok: False, error: str} on failure.
    Used by the onboarding flow to validate keys before persisting.
    """
    body = await request.json()
    provider = (body.get("provider") or "").lower()
    api_key = body.get("api_key")
    if not provider or not api_key:
        return {"ok": False, "error": "provider and api_key are required"}

    try:
        if provider == "openai":
            import openai
            client = openai.AsyncOpenAI(api_key=api_key)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return {"ok": bool(resp.choices)}
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            resp = await client.messages.create(
                model="claude-3-5-haiku-latest",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return {"ok": bool(resp.content)}
        if provider == "google":
            import httpx
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models"
                f"?key={api_key}"
            )
            async with httpx.AsyncClient(timeout=10.0) as http:
                r = await http.get(url)
                if r.status_code == 200:
                    return {"ok": True}
                return {"ok": False, "error": f"HTTP {r.status_code}"}
        if provider == "deepseek":
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as http:
                r = await http.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                if r.status_code == 200:
                    return {"ok": True}
                return {"ok": False, "error": f"HTTP {r.status_code}"}
        return {"ok": False, "error": f"unknown provider: {provider}"}
    except Exception as e:
        logger.info("llm_test failed: %s", e)
        return {"ok": False, "error": str(e)}


# --- Sandbox inspection endpoints ---

@router.get("/sandbox/health")
async def sandbox_health(request: Request) -> dict[str, Any]:
    """Inspect the active sandbox backend."""
    sandbox = _get_sandbox(request.app)
    return await sandbox.health()


@router.get("/sandbox/audit")
async def sandbox_audit(
    request: Request,
    agent: str = "", status: str = "",
    hours: int = 24, limit: int = 100,
) -> dict[str, Any]:
    """Recent audit log entries (defaults: last 24h, 100 rows)."""
    _get_sandbox(request.app)  # ensure audit_log exists
    import time as _t
    since = _t.time() - max(1, hours) * 3600
    rows = request.app.state.sandbox_audit.query(
        agent=agent or None,
        status=status or None,
        since=since,
        limit=max(1, min(limit, 1000)),
    )
    return {"results": rows, "count": len(rows), "since_hours": hours}


@router.get("/sandbox/stats")
async def sandbox_stats(request: Request, hours: int = 24) -> dict[str, Any]:
    """Aggregate dispatch stats per agent over the last N hours."""
    _get_sandbox(request.app)
    import time as _t
    since = _t.time() - max(1, hours) * 3600
    stats = request.app.state.sandbox_audit.stats_by_agent(since=since)
    return {"results": stats, "count": len(stats), "since_hours": hours}


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    """Get current settings."""
    import os
    return {
        "llm": {
            "provider": os.environ.get("LLM_PROVIDER", "openai"),
            "openai_key": _mask_key(os.environ.get("OPENAI_API_KEY", "")),
            "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "anthropic_key": _mask_key(os.environ.get("ANTHROPIC_API_KEY", "")),
            "anthropic_model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "google_key": _mask_key(os.environ.get("GOOGLE_API_KEY", "")),
            "google_model": os.environ.get("GOOGLE_MODEL", "gemini-3.1-pro"),
            "deepseek_key": _mask_key(os.environ.get("DEEPSEEK_API_KEY", "")),
            "deepseek_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v3.2"),
        },
        "tts": {
            "provider": os.environ.get("KALI_TTS_PROVIDER", "auto"),
            "elevenlabs_voice_id": os.environ.get("ELEVENLABS_VOICE_ID", ""),
            "elevenlabs_key": _mask_key(os.environ.get("ELEVENLABS_API_KEY", "")),
        },
        "voice": {
            "wake_word": getattr(getattr(getattr(request.app.state, "config_manager", None), "config", None), "voice", None) and request.app.state.config_manager.config.voice.wake_word or os.environ.get("WAKE_WORD", "jarvis"),
            "mode": os.environ.get("VOICE_MODE", "wake_word"),
            "stt_model": os.environ.get("STT_MODEL", "base"),
        },
        "language": os.environ.get("KALI_LANGUAGE", "ru"),
        # Onboarding gate: frontend reads this to decide whether to show
        # the welcome flow. Stored in .env as KALI_ONBOARDING_COMPLETED.
        "onboarding_completed": os.environ.get("KALI_ONBOARDING_COMPLETED", "").lower() == "true",
    }


@router.post("/settings")
async def update_settings(request: Request) -> dict[str, Any]:
    """Update settings. Persists API keys to .env file."""
    import os
    body = await request.json()

    updates: dict[str, str] = {}
    if "openai_key" in body and body["openai_key"] and not body["openai_key"].startswith("sk-***"):
        os.environ["OPENAI_API_KEY"] = body["openai_key"]
        updates["OPENAI_API_KEY"] = body["openai_key"]
    if "anthropic_key" in body and body["anthropic_key"] and not body["anthropic_key"].startswith("sk-***"):
        os.environ["ANTHROPIC_API_KEY"] = body["anthropic_key"]
        updates["ANTHROPIC_API_KEY"] = body["anthropic_key"]
    if "google_key" in body and body["google_key"] and not body["google_key"].startswith("AI***"):
        os.environ["GOOGLE_API_KEY"] = body["google_key"]
        updates["GOOGLE_API_KEY"] = body["google_key"]
    if "deepseek_key" in body and body["deepseek_key"] and not body["deepseek_key"].startswith("sk-***"):
        os.environ["DEEPSEEK_API_KEY"] = body["deepseek_key"]
        updates["DEEPSEEK_API_KEY"] = body["deepseek_key"]
    if "openai_model" in body:
        os.environ["OPENAI_MODEL"] = body["openai_model"]
        updates["OPENAI_MODEL"] = body["openai_model"]
    if "anthropic_model" in body:
        os.environ["ANTHROPIC_MODEL"] = body["anthropic_model"]
        updates["ANTHROPIC_MODEL"] = body["anthropic_model"]
    if "google_model" in body:
        os.environ["GOOGLE_MODEL"] = body["google_model"]
        updates["GOOGLE_MODEL"] = body["google_model"]
    if "deepseek_model" in body:
        os.environ["DEEPSEEK_MODEL"] = body["deepseek_model"]
        updates["DEEPSEEK_MODEL"] = body["deepseek_model"]
    if "provider" in body:
        os.environ["LLM_PROVIDER"] = body["provider"]
        updates["LLM_PROVIDER"] = body["provider"]
    if "language" in body:
        os.environ["KALI_LANGUAGE"] = body["language"]
        updates["KALI_LANGUAGE"] = body["language"]
    if "onboarding_completed" in body:
        value = "true" if body["onboarding_completed"] else "false"
        os.environ["KALI_ONBOARDING_COMPLETED"] = value
        updates["KALI_ONBOARDING_COMPLETED"] = value

    # Agent credentials (Telegram/Notion/Todoist/smart-home). Only env
    # names in the registry whitelist are accepted, so a request can't set
    # arbitrary environment variables. Masked values (read-back) are
    # skipped so a re-save of the settings form doesn't clobber a real key.
    from kernel.agent_keys import ALLOWED_AGENT_KEYS
    for key in ALLOWED_AGENT_KEYS:
        if key in body and body[key] and "***" not in str(body[key]):
            os.environ[key] = str(body[key])
            updates[key] = str(body[key])

    if updates:
        _save_env(updates)

    return {"status": "updated", "keys": list(updates.keys())}
