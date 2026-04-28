# ruff: noqa: E501  # LLM_SYSTEM_PROMPT contains verbatim prompt lines >100 chars; reflow would break A4 fidelity
"""LLM-driven single-shot extraction over the wizard schema.

Used by `POST /builder/extract` to populate as many wizard answers as
possible from a single user utterance — the A4 fast-path. When the LLM
returns enough data to fill every wizard slot, we skip the wizard
entirely and produce a complete spec; otherwise we pre-populate the
session and return the first un-extracted question to the caller.

Falls back to the regular `BuilderFlow.start()` path if the LLM is
unavailable, returns invalid JSON, or selects an unknown template.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from kernel.builder.intent_classifier import IntentResult, classify_intent
from kernel.builder.session_store import SessionStore
from kernel.builder.wizard import _question_to_key, create_wizard

logger = logging.getLogger(__name__)


LLM_SYSTEM_PROMPT = """\
You are KALI's skill spec extractor. The user describes a Russian (or
English) automation idea; your job is to extract every parameter that
can be derived from their words and return a complete or partial skill
spec.

Templates and their config keys:
- tracker:   interval (e.g. "2 часа", "час"), goal (e.g. "2 литра"), notify_channel ("голос" | "телеграм" | "чат")
- reminder:  interval, time_window (e.g. "9-22", "будни")
- monitor:   target (URL or service), interval
- notifier:  trigger, notify_channel
- logger:    categories

Use ONLY data the user provided. Do NOT invent values. If a parameter
is not stated, omit the key entirely (do not write null).

Respond with STRICT JSON only, no prose:
{
  "type": "skill",
  "template": "<one of: tracker | reminder | monitor | notifier | logger>",
  "name_hint": "<kebab-case slug, lowercase, ≤40 chars>",
  "extracted": {
    "interval": "<string>",
    "goal": "<string>",
    "notify_channel": "<string>",
    "time_window": "<string>",
    "target": "<string>",
    "trigger": "<string>",
    "categories": "<string>"
  },
  "confidence": <0.0-1.0>
}

Only include keys you actually extracted under "extracted".
"""


_VALID_TEMPLATES = frozenset({"tracker", "reminder", "monitor", "notifier", "logger"})


def _call_llm(request: str) -> dict[str, Any] | None:
    """Run the extractor prompt against the configured LLM provider.

    Returns the parsed JSON dict on success, or None if no provider is
    configured / call fails / response is not valid JSON.
    """
    try:
        from kernel.builder.agent_generator import _detect_provider, _call_llm as call
    except ImportError:
        logger.warning("agent_generator not importable — extractor disabled")
        return None

    provider_info = _detect_provider()
    if provider_info is None:
        return None

    provider, model = provider_info
    try:
        raw = call(provider, model, LLM_SYSTEM_PROMPT, request)
    except Exception as exc:
        logger.warning("Extractor LLM call failed (%s): %s", provider, exc)
        return None

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Extractor LLM returned invalid JSON: %s — %s", exc, raw[:200])
        return None


def extract_spec(
    request: str,
    session_store: SessionStore,
) -> dict[str, Any]:
    """Single-shot extract → either a complete spec or a partially-filled session.

    Args:
        request: User's natural-language description.
        session_store: Where the new session is created.

    Returns:
        Dict matching the `/builder/extract` HTTP contract — see spec.
    """
    llm_result = _call_llm(request)

    # Fallback: LLM unavailable, returned non-dict / invalid JSON, or unknown template.
    if (
        llm_result is None
        or not isinstance(llm_result, dict)
        or llm_result.get("template") not in _VALID_TEMPLATES
    ):
        return _fallback_to_start(request, session_store)

    template = llm_result["template"]
    name_hint = llm_result.get("name_hint") or None
    extracted = llm_result.get("extracted") or {}
    if not isinstance(extracted, dict):
        extracted = {}  # defensive against LLM emitting a list / scalar

    intent = IntentResult(
        type="skill",
        template=template,
        confidence=float(llm_result.get("confidence", 0.75)),
        reason="LLM extractor",
    )
    wizard = create_wizard(request, intent)

    # Walk questions in order, fill answers from `extracted` until the first
    # missing field; preserves wizard order so the user resumes at the right
    # step.
    sid = session_store.create(
        request=request,
        intent_type="skill",
        template=template,
    )
    session = session_store.get(sid)
    session.questions = wizard.questions
    session.name_hint = name_hint

    for question in session.questions:
        key = _question_to_key(question)
        if key and key in extracted:
            session.answers.append(extracted[key])
            session.step += 1
        else:
            break

    if session.step == len(session.questions):
        # All extracted — build spec immediately.
        from kernel.builder.flow import BuilderFlow

        flow = BuilderFlow.__new__(BuilderFlow)
        spec = flow._build_spec(session)
        session.spec = spec
        return {"complete": True, "session_id": sid, "spec": spec}

    # Partial — return next question + partial preview spec.
    from kernel.builder.flow import BuilderFlow

    flow = BuilderFlow.__new__(BuilderFlow)
    partial_spec = flow._build_spec(session)

    return {
        "complete": False,
        "session_id": sid,
        "step": session.step,
        "total_steps": len(session.questions),
        "questions": list(session.questions),  # full list — UI uses this for editField
        "next_question": session.current_question,
        "partial_spec": partial_spec,
    }


def _fallback_to_start(request: str, session_store: SessionStore) -> dict[str, Any]:
    """Mirror BuilderFlow.start() — used when LLM extraction fails."""
    intent = classify_intent(request)
    if intent.type != "skill":
        # Pilot scope guard — same as BuilderFlow.start().
        raise ValueError(
            f"Agent generation out of pilot scope (got intent: {intent.type})"
        )
    wizard = create_wizard(request, intent)
    sid = session_store.create(
        request=request,
        intent_type="skill",
        template=intent.template,
    )
    session = session_store.get(sid)
    session.questions = wizard.questions

    from kernel.builder.flow import BuilderFlow

    flow = BuilderFlow.__new__(BuilderFlow)
    partial_spec = flow._build_spec(session)

    return {
        "complete": False,
        "session_id": sid,
        "step": 0,
        "total_steps": len(session.questions),
        "questions": list(session.questions),  # full list — UI uses this for editField
        "next_question": session.current_question,
        "partial_spec": partial_spec,
    }
