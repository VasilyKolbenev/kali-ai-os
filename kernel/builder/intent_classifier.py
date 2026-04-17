"""Intent classifier — determines whether a user request needs a skill or a full agent.

Hybrid mode:
- LLM mode (preferred): uses the configured LLM provider for semantic understanding
- Regex fallback: when no API key configured or LLM call fails
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Template pattern groups: (template_name, list_of_regex_patterns)
_TEMPLATE_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "tracker",
        [r"отслеж", r"трек", r"учёт", r"учет", r"считай", r"считать", r"track"],
    ),
    (
        "reminder",
        [r"напомин", r"remind"],
    ),
    (
        "monitor",
        [r"монитор", r"проверяй", r"check\s+every", r"monitor"],
    ),
    (
        "notifier",
        [r"уведом", r"notify", r"alert"],
    ),
    (
        "logger",
        [r"журнал", r"дневник", r"diary", r"log"],
    ),
]

_AGENT_SIGNALS: list[str] = [
    r"api", r"парс", r"integrat", r"интегр",
    r"home\s+assistant", r"telegram", r"email",
    r"крипт", r"биржа", r"авиа", r"билет",
]

_LLM_SYSTEM_PROMPT = """\
You are KALI's intent classifier. Given a user request, decide:
- type: "skill" (simple YAML-config automation) or "agent" (needs custom Python code)
- template (only if type=skill): one of "tracker", "reminder", "monitor", "notifier", "logger"

Use "skill" when the request fits a template:
- tracker: counting/tracking values (water, habits, expenses)
- reminder: time-based reminders
- monitor: periodic URL/API checks with alerts
- notifier: conditional notifications
- logger: event/diary logging

Use "agent" when the request needs:
- Custom API integration (Telegram, Home Assistant, crypto exchanges)
- Complex parsing or data transformation
- Multi-step logic that templates can't express

Respond with STRICT JSON only, no prose:
{"type": "skill"|"agent", "template": "tracker"|"reminder"|"monitor"|"notifier"|"logger"|null, "confidence": 0.0-1.0, "reason": "short explanation"}
"""


@dataclass
class IntentResult:
    """Classification result."""

    type: str  # "skill" | "agent"
    template: str | None
    confidence: float
    reason: str


def _classify_regex(request: str) -> IntentResult:
    """Regex-only classification (fallback when LLM unavailable)."""
    text = request.lower()

    for signal in _AGENT_SIGNALS:
        if re.search(signal, text):
            return IntentResult(
                type="agent", template=None, confidence=0.85,
                reason=f"Agent signal detected: '{signal}' [regex]",
            )

    for template_name, patterns in _TEMPLATE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                return IntentResult(
                    type="skill", template=template_name, confidence=0.80,
                    reason=f"Matched '{template_name}' via '{pattern}' [regex]",
                )

    return IntentResult(
        type="skill", template=None, confidence=0.50,
        reason="No pattern matched; defaulting to skill [regex]",
    )


def _classify_llm(request: str) -> IntentResult | None:
    """LLM-based classification. Returns None if no provider or call fails."""
    try:
        from kernel.builder.agent_generator import _detect_provider, _call_llm
    except ImportError:
        return None

    provider_info = _detect_provider()
    if provider_info is None:
        return None

    provider, model = provider_info
    try:
        raw = _call_llm(provider, model, _LLM_SYSTEM_PROMPT, request)
    except Exception as exc:
        logger.warning("LLM intent classification failed (%s): %s", provider, exc)
        return None

    # Strip possible markdown fences
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned invalid JSON: %s — %s", exc, raw[:200])
        return None

    type_ = data.get("type")
    if type_ not in ("skill", "agent"):
        return None

    template = data.get("template")
    if template == "null" or not template:
        template = None

    return IntentResult(
        type=type_,
        template=template,
        confidence=float(data.get("confidence", 0.75)),
        reason=f"{data.get('reason', 'LLM classification')} [{provider}]",
    )


def classify_intent(request: str) -> IntentResult:
    """Classify a natural-language request.

    Tries LLM first for semantic understanding, falls back to regex patterns.

    Args:
        request: Natural-language description from the user.

    Returns:
        IntentResult with type, template, confidence, and reason.
    """
    llm_result = _classify_llm(request)
    if llm_result is not None:
        logger.info("Intent: %s/%s (%.2f) via LLM — %s",
                    llm_result.type, llm_result.template, llm_result.confidence, llm_result.reason)
        return llm_result

    regex_result = _classify_regex(request)
    logger.info("Intent: %s/%s (%.2f) via regex — %s",
                regex_result.type, regex_result.template, regex_result.confidence, regex_result.reason)
    return regex_result
