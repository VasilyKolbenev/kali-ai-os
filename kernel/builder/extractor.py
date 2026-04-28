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

from kernel.builder.intent_classifier import IntentResult  # noqa: F401  # Task 5: extract_spec
from kernel.builder.session_store import BuilderSession, SessionStore  # noqa: F401  # Task 5
from kernel.builder.wizard import _question_to_key, create_wizard  # noqa: F401  # Task 5

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
