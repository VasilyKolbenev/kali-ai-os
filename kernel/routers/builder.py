"""Builder endpoints (voice/skill/agent builder flow) — extracted from
kernel/main.py (T6).

Bodies are byte-identical to the pre-split closures except the sanctioned
signature changes (plan 2026-07-13 (c)): the ``resolved_agents_dir`` closure
in create-skill/create-agent became ``request.app.state.agents_dir`` (set in
create_app, T0 amendment (a)). Def order preserves main.py registration order.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from kernel.builder.intent_classifier import classify_intent
from kernel.builder.skill_generator import generate_skill
from kernel.builder.agent_generator import generate_agent
from kernel.builder.safety_gate import check_code
from kernel.builder.deployer import deploy_skill, deploy_agent

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/builder/classify")
async def builder_classify(request: Request) -> dict[str, Any]:
    """Classify user request as skill or agent."""
    body = await request.json()
    text = body.get("text", "")
    result = classify_intent(text)
    return {
        "type": result.type,
        "template": result.template,
        "confidence": result.confidence,
        "reason": result.reason,
    }


@router.post("/builder/create-skill")
async def builder_create_skill(request: Request) -> dict[str, Any]:
    """Generate and deploy a skill."""
    body = await request.json()
    name = body["name"]
    template = body["template"]
    description = body.get("description", name)
    config = body.get("config", {})

    skill_dir = generate_skill(
        name=name,
        template=template,
        description=description,
        config=config,
        agents_dir=request.app.state.agents_dir,
    )
    return await deploy_skill(
        skill_dir,
        request.app.state.skill_executor,
        getattr(request.app.state, "scheduler", None),
    )


@router.post("/builder/create-agent")
async def builder_create_agent(request: Request) -> dict[str, Any]:
    """Generate, validate, and deploy an agent."""
    import shutil

    body = await request.json()
    name = body["name"]
    description = body["description"]
    tools = body.get("tools", [])
    apis = body.get("apis", [])

    agent_dir = generate_agent(
        name=name,
        description=description,
        tools=tools,
        apis=apis,
        agents_dir=request.app.state.agents_dir,
    )
    if not agent_dir:
        return {"status": "error", "message": "Agent generation failed"}

    # Safety gate
    code = (agent_dir / "agent.py").read_text()
    safety = check_code(code)
    if not safety.safe:
        shutil.rmtree(agent_dir)
        return {"status": "unsafe", "issues": safety.issues}

    return await deploy_agent(
        agent_dir,
        request.app.state.plugin_registry,
        request.app.state.agent_runtime,
    )


@router.post("/builder/start")
async def builder_start(request: Request) -> Any:
    """Start a builder flow from a natural-language request.

    Expects JSON body with ``request`` (str). Returns session metadata
    including the first clarifying question and total wizard steps.
    """
    from fastapi.responses import JSONResponse

    body = await request.json()
    text = (body.get("request") or "").strip()
    if not text:
        return JSONResponse({"error": "request must be non-empty"}, status_code=400)

    try:
        return request.app.state.builder_flow.start(text)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("builder/start failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/builder/extract")
async def builder_extract(request: Request) -> Any:
    """A4 fast-path: single-shot LLM extraction over the wizard schema.

    Tries to populate every wizard answer from the user utterance in
    one LLM call. On full match returns the complete spec; on partial
    match returns a session pre-populated up to the first missing
    field plus the next question; on failure / invalid template /
    LLM unavailable, silently falls back to `/builder/start` shape.
    """
    from fastapi.responses import JSONResponse
    from kernel.builder.extractor import extract_spec

    body = await request.json()
    text = (body.get("request") or "").strip()
    if not text:
        return JSONResponse({"error": "request must be non-empty"}, status_code=400)

    try:
        return extract_spec(
            request=text,
            session_store=request.app.state.builder_flow._store,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("/builder/extract failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/builder/answer")
async def builder_answer(request: Request) -> Any:
    """Record an answer in the active builder wizard.

    Expects JSON body with ``session_id`` (str) and ``answer`` (str).
    Returns next question dict while wizard is in progress, or a preview
    dict once all questions are answered.
    """
    from fastapi.responses import JSONResponse
    from kernel.builder.session_store import SessionNotFound

    body = await request.json()
    sid = body.get("session_id", "")
    text = (body.get("answer") or "").strip()
    if not sid or not text:
        return JSONResponse(
            {"error": "session_id and answer required"}, status_code=400
        )

    try:
        return request.app.state.builder_flow.answer(sid, text)
    except SessionNotFound:
        return JSONResponse(
            {"error": "session not found or expired"}, status_code=404
        )


@router.post("/builder/deploy")
async def builder_deploy(request: Request) -> Any:
    """Materialise and deploy the skill built in this session.

    Expects JSON body with ``session_id`` (str). The wizard must be
    complete (all answers provided) before deploying.
    """
    from fastapi.responses import JSONResponse
    from kernel.builder.session_store import SessionNotFound

    body = await request.json()
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    try:
        return await request.app.state.builder_flow.deploy(sid)
    except SessionNotFound:
        return JSONResponse({"error": "session not found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/builder/cancel")
async def builder_cancel(request: Request) -> Any:
    """Abort an in-flight builder session.

    Expects JSON body with ``session_id`` (str). No-op if the session is
    already gone; always returns ``{"status": "cancelled"}``.
    """
    from fastapi.responses import JSONResponse

    body = await request.json()
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    request.app.state.builder_flow.cancel(sid)
    return {"status": "cancelled"}
