"""Catalog + community endpoints — extracted from kernel/main.py (T4).

Bodies are byte-identical to the pre-split closures except the sanctioned
signature changes (plan 2026-07-13 (c)): ``/catalog/pack/{name}`` gained
``request: Request``; the ``resolved_agents_dir`` closure became
``request.app.state.agents_dir`` (set in create_app, T0 amendment (a));
``_get_skills_catalog`` (routers/_shared) takes ``request.app`` explicitly.

Def order preserves main.py registration order (sacred, amendment (d)):
``/catalog/pack/{name}`` and ``/catalog/community/install`` register BEFORE
the ``/catalog/{slug}/*`` block; ``/catalog/moderation/*`` stays after it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from kernel.catalog.installer import install_package
from kernel.catalog.package import pack as pack_agent, get_package_info
from kernel.routers._shared import _get_skills_catalog

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/catalog/search")
async def catalog_search(request: Request, q: str = "", category: str = "") -> dict[str, Any]:
    """Search catalog — local agents first, then cloud."""
    client = request.app.state.catalog_client
    local = await client.local_search(q, request.app.state.agents_dir) if q else []
    cloud = await client.search(q, category=category or None) if q else []
    local_names = {r["name"] for r in local}
    results = local + [c for c in cloud if c.get("name") not in local_names]
    return {"results": results, "count": len(results)}


@router.post("/catalog/pack/{name}")
async def catalog_pack(name: str, request: Request) -> dict[str, Any]:
    """Pack agent/skill into .kali-agent file."""
    agent_dir = request.app.state.agents_dir / name
    if not agent_dir.exists():
        return {"error": f"Agent '{name}' not found"}
    try:
        Path("exports").mkdir(exist_ok=True)
        output = pack_agent(agent_dir, Path("exports") / f"{name}.kali-agent")
        return {"status": "packed", "path": str(output)}
    except Exception as e:
        return {"error": str(e)}


@router.post("/catalog/install")
async def catalog_install(request: Request) -> dict[str, Any]:
    """Install from .kali-agent file."""
    from fastapi.responses import JSONResponse

    body = await request.json()
    path = Path(body.get("path", ""))
    if path.suffix != ".kali-agent":
        return JSONResponse({"error": "Must be a .kali-agent file"}, status_code=400)
    if not path.exists():
        return {"error": f"File not found: {path}"}
    result = await install_package(
        path,
        agents_dir=request.app.state.agents_dir,
        skill_executor=getattr(request.app.state, "skill_executor", None),
        plugin_registry=getattr(request.app.state, "plugin_registry", None),
        agent_runtime=getattr(request.app.state, "agent_runtime", None),
    )
    return result


@router.get("/catalog/info")
async def catalog_info(path: str = "") -> dict[str, Any]:
    """Get package info without installing."""
    p = Path(path)
    if not p.exists():
        return {"error": "File not found"}
    try:
        return get_package_info(p)
    except Exception as e:
        return {"error": str(e)}


@router.get("/catalog/trending")
async def catalog_trending(request: Request) -> dict[str, Any]:
    """Trending — cloud packages, or local agents as fallback."""
    client = request.app.state.catalog_client
    cloud = await client.trending()
    if cloud:
        return {"results": cloud}
    local = await client.local_search("", request.app.state.agents_dir)
    return {"results": local}


@router.get("/catalog/community")
async def catalog_community(request: Request, q: str = "") -> dict[str, Any]:
    """Merged «Сообщество» feed: Supabase ``approved`` UGC ∪ GitHub curated.

    Returns one deduped, source-tagged card list (``source`` ∈
    ``ugc``/``curated``/``local``) so the tab renders a single card surface.
    UGC cards carry the §4 social counts (likes/ratings) + creator handle;
    curated cards carry the GitHub install handle (``source_id``+``name``).

    Graceful degradation (preserved contract): when Supabase is
    unconfigured/offline the UGC list is ``[]`` (``CatalogClient.browse``
    already degrades), so the feed becomes curated ∪ locally-installed with
    NO error wall. A failed GitHub refresh likewise yields the cached/empty
    curated set rather than raising.

    Args:
        q: Optional case-insensitive substring filter over name/description.
    """
    from kernel.catalog.merge import merge_community

    client = request.app.state.catalog_client

    # Supabase approved UGC (search when a query is given, else browse all).
    ugc = await (client.search(q) if q else client.browse())

    # GitHub curated shelf — refresh the curated source so a cold start has
    # data; refresh_source returns cached/[] on a network failure (no raise).
    catalog = _get_skills_catalog(request.app)
    curated_dicts: list[dict[str, Any]] = []
    try:
        catalog.refresh_source("kali")
        entries = catalog.list_by_source("kali")
        if q:
            qlow = q.lower()
            entries = [
                e for e in entries
                if qlow in e.name.lower() or qlow in e.description.lower()
            ]
        curated_dicts = [e.to_dict() for e in entries]
    except Exception as exc:  # noqa: BLE001 — degrade to no curated set
        logger.warning("community: curated refresh failed: %s", exc)

    # Locally-installed agents — the offline fallback so the tab is never
    # empty/error-walled when Supabase is down.
    local = await client.local_search(q, request.app.state.agents_dir)

    # Enrich UGC cards with live social counts (best-effort; missing → zeros).
    social_by_slug: dict[str, dict[str, Any]] = {}
    for row in ugc:
        slug = (row.get("slug") or "").strip()
        if not slug:
            continue
        try:
            social_by_slug[slug] = await client.get_social(slug)
        except Exception:  # noqa: BLE001 — a missing aggregate degrades to zeros
            continue

    results = merge_community(
        ugc, curated_dicts, local, social_by_slug=social_by_slug
    )
    return {"results": results, "count": len(results)}


@router.post("/catalog/community/install")
async def catalog_community_install(request: Request) -> dict[str, Any]:
    """Install a Supabase UGC skill by slug (download bundle → live install).

    Body: ``{"slug": "<skills.slug>"}``. Routes through
    ``CatalogClient.install_skill`` (Storage download → AST safety gate →
    register into the live runtime) and records an install attribution.
    Degrades to ``{"status": "unconfigured"}`` when Supabase is offline.
    Curated GitHub cards use ``/skills/install`` (source_id+name) instead.
    """
    from fastapi.responses import JSONResponse

    body = await request.json()
    slug = (body or {}).get("slug", "").strip()
    if not slug:
        return JSONResponse(
            status_code=400, content={"status": "error", "reason": "slug_required"}
        )
    client = request.app.state.catalog_client
    result = await client.install_skill(
        slug,
        agents_dir=request.app.state.agents_dir,
        plugin_registry=getattr(request.app.state, "plugin_registry", None),
        skill_executor=getattr(request.app.state, "skill_executor", None),
        agent_runtime=getattr(request.app.state, "agent_runtime", None),
    )
    # Best-effort attribution (no PII) — never block the install on a counter.
    if result.get("status") not in {"unconfigured", "error"}:
        try:
            await client.record_install(slug)
        except Exception:  # noqa: BLE001 — attribution is best-effort
            pass
    return result


# --- Community account (magic-link sign-in, WS-3 Task 3.3/3.5) ---
# KALI's OWN account: email → Supabase magic-link OTP. NEVER Google/Apple
# OAuth (§7 anti-pivot). Anonymous browse/install/like need no account; only
# rate/comment are account-gated — these routes surface the honest sign-in
# prompt the UI shows when a signed-out write returns "sign-in required".

@router.get("/community/account")
async def community_account(request: Request) -> dict[str, Any]:
    """Report the current KALI account session (signed-in id, if any).

    Returns ``{"signed_in": bool, "account_id": str | None}`` — used by the
    community UI to decide whether a rate/comment needs the sign-in prompt.
    Degrades to signed-out when Supabase is offline.
    """
    identity = request.app.state.catalog_client.identity
    account_id = identity.current_account_id()
    return {"signed_in": account_id is not None, "account_id": account_id}


@router.post("/community/account/magic-link")
async def community_magic_link(request: Request) -> dict[str, Any]:
    """Send a magic-link / OTP email (Supabase ``sign_in_with_otp``).

    Body: ``{"email": "<address>"}``. Returns the identity layer result
    VERBATIM (``{"status": "sent"}`` / ``"unconfigured"`` / ``"error"``) so
    the UI shows honest status — never a fake success. NOT OAuth.
    """
    from fastapi.responses import JSONResponse

    body = await request.json()
    email = (body or {}).get("email", "").strip()
    if not email:
        return JSONResponse(
            status_code=400, content={"status": "error", "reason": "email_required"}
        )
    return request.app.state.catalog_client.identity.request_magic_link(email)


@router.post("/community/account/verify")
async def community_verify(request: Request) -> dict[str, Any]:
    """Exchange the emailed OTP for a session (Supabase ``verify_otp``).

    Body: ``{"email": "<address>", "token": "<code>"}``. Returns the identity
    result verbatim (``{"status": "signed_in"}`` / ``"error"`` / ...).
    """
    from fastapi.responses import JSONResponse

    body = await request.json()
    email = (body or {}).get("email", "").strip()
    token = (body or {}).get("token", "").strip()
    if not email or not token:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reason": "email_and_token_required"},
        )
    return request.app.state.catalog_client.identity.verify_magic_link(email, token)


@router.post("/community/account/sign-out")
async def community_sign_out(request: Request) -> dict[str, Any]:
    """Sign out of the KALI account + clear the persisted session."""
    return request.app.state.catalog_client.identity.sign_out()


# --- Community social layer (like / rate / comment, WS-3 Task 3.4) ---
# Each route returns the CatalogClient result VERBATIM so an honest
# "sign-in required" (rate/comment when signed out) reaches the UI as such,
# never a fake success. Likes are anon (device-id); rate/comment are
# account-gated inside the client. All degrade gracefully when offline.

@router.post("/catalog/{slug}/like")
async def catalog_like(slug: str, request: Request) -> dict[str, Any]:
    """Like a skill as the anonymous local device (idempotent, no sign-in)."""
    return await request.app.state.catalog_client.like(slug)


@router.delete("/catalog/{slug}/like")
async def catalog_unlike(slug: str, request: Request) -> dict[str, Any]:
    """Remove this device's like from a skill."""
    return await request.app.state.catalog_client.unlike(slug)


@router.post("/catalog/{slug}/rating")
async def catalog_rating(slug: str, request: Request) -> dict[str, Any]:
    """Set this account's 1-5 star rating (account-gated; honest sign-in)."""
    body = await request.json()
    return await request.app.state.catalog_client.set_rating(
        slug, body.get("stars")
    )


@router.post("/catalog/{slug}/comment")
async def catalog_comment(slug: str, request: Request) -> dict[str, Any]:
    """Post a comment (account-gated; defaults to pending moderation)."""
    body = await request.json()
    return await request.app.state.catalog_client.post_comment(
        slug, body.get("body", "")
    )


@router.get("/catalog/{slug}/comments")
async def catalog_comments(slug: str, request: Request) -> dict[str, Any]:
    """List a skill's approved comments (newest first)."""
    comments = await request.app.state.catalog_client.list_comments(slug)
    return {"comments": comments}


@router.get("/catalog/{slug}/social")
async def catalog_social(slug: str, request: Request) -> dict[str, Any]:
    """Aggregate a skill's social signals (likes + ratings + viewer state)."""
    return await request.app.state.catalog_client.get_social(slug)


# --- Community moderation lifecycle (WS-3 Task 3.7, §5C) ---
# The report route is PUBLIC (the report button — anon or signed-in). The
# status-transition + queue routes are MODERATION-ONLY: gated behind
# `_require_moderator`, which checks an `X-Moderator-Token` header against the
# KALI_MODERATOR_TOKEN env/config flag and returns 403 otherwise. This is the
# auth SEAM only — the real moderation authority is a human gate (Vasily
# reviews at MVP), and the privileged CatalogClient transitions run with the
# Supabase service_role key in production (never the public anon client).

def _require_moderator(request: Request):
    """Return a 403 JSONResponse when the caller is not an authorized moderator.

    Returns None when authorized (the route proceeds). The check is a simple
    shared-secret seam: the `X-Moderator-Token` header must equal the
    `KALI_MODERATOR_TOKEN` env value. When no token is configured the endpoint
    is CLOSED (always 403) — moderation never defaults to open. This is the
    auth seam only; the real authority is a human gate (Vasily at MVP).
    """
    from fastapi.responses import JSONResponse

    expected = os.environ.get("KALI_MODERATOR_TOKEN")
    provided = request.headers.get("x-moderator-token")
    if not expected or not provided or provided != expected:
        return JSONResponse(
            status_code=403,
            content={"status": "forbidden", "reason": "moderator_only"},
        )
    return None


@router.post("/catalog/{slug}/report")
async def catalog_report(slug: str, request: Request) -> dict[str, Any]:
    """File a moderation flag against a skill (PUBLIC report button).

    Body: ``{"reason": "<optional free text>"}``. Reports a skill by slug —
    the client resolves the slug to the skill id; for now the route passes the
    slug through as the target id so the queue carries an actionable handle.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — tolerate an empty/invalid body
        body = {}
    return await request.app.state.catalog_client.report(
        "skill", slug, reason=(body or {}).get("reason")
    )


@router.post("/catalog/{slug}/status")
async def catalog_set_skill_status(slug: str, request: Request):
    """Transition a skill's moderation status (MODERATOR-ONLY).

    Body: ``{"status": "approved"|"flagged"|"removed"|"pending"}``.
    """
    denied = _require_moderator(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await request.app.state.catalog_client.set_skill_status(
        slug, (body or {}).get("status", "")
    )


@router.post("/catalog/comments/{comment_id}/status")
async def catalog_set_comment_status(comment_id: str, request: Request):
    """Transition a comment's moderation status (MODERATOR-ONLY)."""
    denied = _require_moderator(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await request.app.state.catalog_client.set_comment_status(
        comment_id, (body or {}).get("status", "")
    )


@router.get("/catalog/moderation/pending")
async def catalog_list_pending(request: Request):
    """List skills awaiting manual review (MODERATOR-ONLY)."""
    denied = _require_moderator(request)
    if denied is not None:
        return denied
    rows = await request.app.state.catalog_client.list_pending()
    return {"pending": rows}


@router.get("/catalog/moderation/flags")
async def catalog_list_flags(request: Request):
    """List the moderation report queue (MODERATOR-ONLY)."""
    denied = _require_moderator(request)
    if denied is not None:
        return denied
    rows = await request.app.state.catalog_client.list_flags()
    return {"flags": rows}
