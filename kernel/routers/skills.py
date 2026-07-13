"""Skills endpoints (Agent Skills / SKILL.md spec) — extracted from kernel/main.py (T3).

Bodies are byte-identical to the pre-split closures except the sanctioned
signature changes (plan 2026-07-13 (c)): endpoints without ``request: Request``
gained it, bare ``app.`` became ``request.app.``, and the ``_get_skills_*``
helpers (routers/_shared) take ``request.app`` explicitly.

Def order preserves main.py registration order (sacred, amendment (d)):
``/skills/{name}/{action}`` registers BEFORE ``/skills/catalog/refresh`` —
today it shadows it and that is observed behavior.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from kernel.routers._shared import _get_skills_catalog, _get_skills_registry

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/skills")
async def list_skills_route(request: Request) -> list[dict[str, Any]]:
    """List all loaded skills."""
    executor = request.app.state.skill_executor
    return [info for name in executor.list_skills() if (info := executor.get_skill_info(name)) is not None]


@router.post("/skills/{name}/{action}")
async def execute_skill_route(name: str, action: str, request: Request) -> Any:
    """Execute a skill action."""
    body: dict[str, Any] = {}
    if request.headers.get("content-type") == "application/json":
        body = await request.json()
    try:
        result = await request.app.state.skill_executor.execute(name, action, body)
        return result
    except ValueError as e:
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": str(e)}, status_code=404)


# --- Agent Skills (SKILL.md spec) endpoints ---

@router.get("/skills/catalog/sources")
async def skills_catalog_sources(request: Request) -> dict[str, Any]:
    """List configured remote skill sources (for UI tabs)."""
    catalog = _get_skills_catalog(request.app)
    return {
        "sources": [
            {
                "id": s.id, "label": s.label, "trust": s.trust,
                "owner": s.owner, "repo": s.repo, "ref": s.ref,
                "url": s.display_url,
            }
            for s in catalog.sources
        ]
    }


@router.get("/skills/catalog")
async def skills_catalog_list(
    request: Request, source: str = "", q: str = "",
) -> dict[str, Any]:
    """List remote skills, optionally filtered by source_id and/or search query."""
    catalog = _get_skills_catalog(request.app)
    if source:
        entries = catalog.list_by_source(source)
        if q:
            qlow = q.lower()
            entries = [
                e for e in entries
                if qlow in e.name.lower() or qlow in e.description.lower()
            ]
    elif q:
        entries = catalog.search(q)
    else:
        entries = catalog.list_all()
    return {
        "results": [e.to_dict() for e in entries],
        "count": len(entries),
    }


@router.post("/skills/catalog/refresh")
async def skills_catalog_refresh(request: Request) -> dict[str, Any]:
    """Force-refresh the remote catalog index (fetches from GitHub)."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    force = bool(body.get("force", True))
    catalog = _get_skills_catalog(request.app)
    total = catalog.refresh_all(force=force)
    return {"status": "ok", "total_entries": total}


@router.post("/skills/install")
async def skills_install(request: Request) -> dict[str, Any]:
    """Install a skill from the remote catalog.

    Body: {"source_id": "anthropic", "name": "pdf-processing"}
    """
    from kernel.skills.installer import install_from_catalog
    body = await request.json()
    source_id = body.get("source_id", "")
    name = body.get("name", "")
    if not source_id or not name:
        return {"status": "error", "message": "source_id and name are required"}

    catalog = _get_skills_catalog(request.app)
    entry = catalog.get(source_id, name)
    if entry is None:
        return {
            "status": "error",
            "message": f"Skill '{name}' not found in source '{source_id}'",
        }

    try:
        result = install_from_catalog(
            entry,
            allow_overwrite=bool(body.get("overwrite", False)),
        )
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    if result.ok:
        _get_skills_registry(request.app).reload()
        # Wire the installed skill into the live runtime, not just the catalog:
        # register it in the plugin registry (so it shows in /agents) and, if
        # template-backed (skill.yaml), load it into the executor so it can
        # actually run. Previously ONLY the catalog reloaded, so an installed
        # skill was a ghost — visible in "Мои навыки" but unrunnable (2d).
        # register_dir records the real install dir in PluginRegistry._dirs,
        # which _is_callable now consults — so a skill under %APPDATA%/KALI/
        # skills IS offered to the LLM palette, not just agents_dir (Phase A
        # Chunk 1 closed the prior install->LLM-callable gap).
        if result.install_path is not None:
            try:
                request.app.state.plugin_registry.register_dir(result.install_path)
                if (result.install_path / "skill.yaml").exists():
                    request.app.state.skill_executor.load_skill(result.install_path)
            except Exception:
                logger.exception(
                    "Live registration of installed skill '%s' failed", result.skill_name
                )
        return {
            "status": "ok",
            "skill_name": result.skill_name,
            "install_path": str(result.install_path),
            "warnings": result.warnings,
        }
    return {"status": "error", "message": result.error, "skill_name": result.skill_name}


@router.post("/skills/uninstall")
async def skills_uninstall(request: Request) -> dict[str, Any]:
    """Remove a user-installed skill."""
    from kernel.skills.installer import uninstall
    body = await request.json()
    name = body.get("name", "")
    if not name:
        return {"status": "error", "message": "name is required"}
    ok = uninstall(name)
    if ok:
        _get_skills_registry(request.app).reload()
    return {"status": "ok" if ok else "error", "removed": ok}


@router.post("/skills/install-bundle")
async def skills_install_bundle(request: Request) -> dict[str, Any]:
    """Install a skill from a posted base64url(.tar.gz) bundle — the P2P
    share-loop import path.

    Body: {"data": "<base64url>", "name"?: "...", "overwrite"?: false}.
    Held to the same validation + AST safety gate as a catalog install.
    """
    from kernel.skills.installer import install_from_bundle

    body = await request.json()
    data = body.get("data", "")
    if not data:
        return {"status": "error", "message": "data is required"}

    try:
        result = install_from_bundle(
            data,
            expected_name=body.get("name") or None,
            allow_overwrite=bool(body.get("overwrite", False)),
        )
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    if result.ok:
        _get_skills_registry(request.app).reload()
        # Wire the installed skill into the live runtime, not just the catalog:
        # register it in the plugin registry (so it shows in /agents) and, if
        # template-backed (skill.yaml), load it into the executor so it can
        # actually run. Previously ONLY the catalog reloaded, so an installed
        # skill was a ghost — visible in "Мои навыки" but unrunnable (2d).
        # register_dir records the real install dir in PluginRegistry._dirs,
        # which _is_callable now consults — so a skill under %APPDATA%/KALI/
        # skills IS offered to the LLM palette, not just agents_dir (Phase A
        # Chunk 1 closed the prior install->LLM-callable gap).
        if result.install_path is not None:
            try:
                request.app.state.plugin_registry.register_dir(result.install_path)
                if (result.install_path / "skill.yaml").exists():
                    request.app.state.skill_executor.load_skill(result.install_path)
            except Exception:
                logger.exception(
                    "Live registration of installed skill '%s' failed", result.skill_name
                )
        return {
            "status": "ok",
            "skill_name": result.skill_name,
            "install_path": str(result.install_path),
            "warnings": result.warnings,
        }
    return {"status": "error", "message": result.error, "skill_name": result.skill_name}


@router.get("/skills/{name}/export")
async def skills_export(name: str, request: Request) -> dict[str, Any]:
    """Export an installed skill as a portable base64url(.tar.gz) bundle for
    P2P sharing (the UGC share loop). Self-contained — a friend imports it
    via POST /skills/install-bundle with no catalog or server involved.
    """
    import base64
    import tempfile
    from pathlib import Path

    from kernel.skills.publisher import package_skill
    from kernel.skills.validator import validate_frontmatter

    reg = _get_skills_registry(request.app)
    skill = reg.get(name)
    if skill is not None:
        skill_dir = skill.skill_dir
    else:
        # Voice-built agents live under agents_dir (manifest.yaml + skill.yaml,
        # no SKILL.md) and aren't indexed by SkillsRegistry; the live plugin
        # registry tracks every agent's real directory (Phase A share fix).
        skill_dir = request.app.state.plugin_registry.skill_dir_for(name)
    if skill_dir is None:
        return {"status": "error", "message": f"Skill '{name}' not found locally"}

    # Honest-fail: a non-spec name (uppercase / underscore / non-ascii — the
    # voice builder's slugify uses \w without re.ASCII, so Cyrillic survives)
    # would synthesize a SKILL.md the receiver's strict loader rejects on
    # import. Refuse here rather than ship a bundle that dies on the friend.
    if not validate_frontmatter({"name": name, "description": "x"}, expected_name=name).valid:
        return {
            "status": "error",
            "message": (
                f"Agent name '{name}' can't be shared yet — names must be "
                "lowercase latin letters, digits and single hyphens."
            ),
        }

    try:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = package_skill(skill_dir, output_dir=Path(tmp))
            raw = bundle.read_bytes()
    except Exception as exc:
        return {"status": "error", "message": f"Export failed: {exc}"}

    data = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {"status": "ok", "name": name, "data": data, "size": len(raw)}


@router.get("/skills/{name}/reel")
async def skills_reel(name: str, request: Request):
    """Render a 9:16 voice reel (MP4) for a created agent — the UGC share
    hook. Honest-fail JSON envelope on any error (mobile falls back to the
    PNG card). Mirrors /skills/{name}/export resolution + name gate."""
    import shutil
    import tempfile
    from pathlib import Path

    from fastapi.responses import FileResponse, JSONResponse
    from starlette.background import BackgroundTask

    from kernel.llm_router import LLMRouter
    from kernel.reel import generate_reel
    from kernel.share_links import build_import_link
    from kernel.skills.validator import validate_frontmatter

    reg = _get_skills_registry(request.app)
    skill = reg.get(name)
    if skill is not None:
        description = skill.description
    else:
        manifest = request.app.state.plugin_registry.get(name)
        if manifest is None:
            return JSONResponse(
                {"status": "error", "name": name, "message": f"Agent '{name}' not found locally"}
            )
        description = manifest.description
    if not validate_frontmatter(
        {"name": name, "description": "x"}, expected_name=name
    ).valid:
        return JSONResponse({
            "status": "error",
            "name": name,
            "message": (
                f"Agent name '{name}' can't be shared yet — names must be "
                "lowercase latin letters, digits and single hyphens."
            ),
        })
    tmp = None
    try:
        export = await skills_export(name, request)
        if export.get("status") != "ok":
            return JSONResponse(export)
        link = build_import_link(name=name, bundle=export["data"])
        router = LLMRouter(request.app.state.config_manager.config.llm)
        tmp = Path(tempfile.mkdtemp(prefix="kali_reel_"))
        out = await generate_reel(
            name=name, description=description, link=link,
            router=router, out_dir=tmp,
        )
        return FileResponse(
            str(out), media_type="video/mp4", filename=f"{name}.mp4",
            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
        )
    except Exception as exc:  # noqa: BLE001 — honest error, never 500 to user
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        logger.exception("reel render failed for %s", name)
        return JSONResponse(
            {"status": "error", "name": name, "message": f"Reel render failed: {exc}"}
        )


@router.get("/skills/installed")
async def skills_installed(request: Request) -> dict[str, Any]:
    """List all skills discovered locally (builtin + user)."""
    reg = _get_skills_registry(request.app)
    return {
        "results": [m.to_dict() for m in reg.list_all()],
        "count": len(reg.list_all()),
    }


@router.post("/skills/validate")
async def skills_validate(request: Request) -> dict[str, Any]:
    """Validate a local skill against the Agent Skills spec.

    Body: {"name": "my-skill"}  — name of an installed skill.
    """
    from kernel.skills.publisher import validate_skill

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return {"status": "error", "message": "name is required"}

    reg = _get_skills_registry(request.app)
    skill = reg.get(name)
    if skill is None:
        return {"status": "error", "message": f"Skill '{name}' not found locally"}

    manifest, errors, warnings = validate_skill(skill.skill_dir)
    return {
        "status": "ok" if not errors else "invalid",
        "skill_name": name,
        "valid": manifest is not None and not errors,
        "errors": errors,
        "warnings": warnings,
    }


@router.post("/skills/publish")
async def skills_publish(request: Request) -> dict[str, Any]:
    """Prepare a skill bundle for community catalog submission.

    Body: {"name": "my-skill"}

    Returns bundle path + next-step instructions (does not push to GitHub).
    """
    from kernel.skills.publisher import publish_skill

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return {"status": "error", "message": "name is required"}

    reg = _get_skills_registry(request.app)
    skill = reg.get(name)
    if skill is None:
        return {"status": "error", "message": f"Skill '{name}' not found locally"}

    # skip_safety is NOT exposed over HTTP — the AST safety gate must always
    # run on a publish path (it is an internal/testing-only kwarg).
    result = publish_skill(
        skill.skill_dir,
        skip_safety=False,
        include_scripts=bool(body.get("include_scripts", True)),
    )

    response: dict[str, Any] = {
        "status": "ok" if result.ok else "error",
        "skill_name": result.skill_name,
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "safety_issues": result.safety_issues,
        "catalog_repo_url": result.catalog_repo_url,
        "instructions": result.instructions,
    }
    if result.bundle_path:
        response["bundle_path"] = str(result.bundle_path)
        response["bundle_name"] = result.bundle_path.name
    return response
