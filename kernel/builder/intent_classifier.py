"""Intent classifier — determines whether a user request needs a skill or a full agent."""

from __future__ import annotations

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

# Signals that suggest a full agent (code) is required
_AGENT_SIGNALS: list[str] = [
    r"api",
    r"парс",
    r"integrat",   # English: integrate, integration
    r"интегр",     # Russian: интегрировать, интеграция
    r"home\s+assistant",
    r"telegram",
    r"email",
    r"крипт",
    r"биржа",
    r"авиа",
    r"билет",
]


@dataclass
class IntentResult:
    """Result of classifying a user intent.

    Attributes:
        type: Either "skill" (YAML template) or "agent" (needs code).
        template: Template name when type is "skill", else None.
        confidence: Float in [0.0, 1.0] indicating classification confidence.
        reason: Human-readable explanation of the decision.
    """

    type: str  # "skill" | "agent"
    template: str | None
    confidence: float
    reason: str


def classify_intent(request: str) -> IntentResult:
    """Classify a natural-language request as skill or agent.

    First checks for agent signals (API/integration mentions). If found,
    returns an agent result immediately. Otherwise matches against known
    template patterns. Defaults to "skill" when ambiguous.

    Args:
        request: Natural-language description from the user.

    Returns:
        IntentResult with type, template, confidence, and reason.
    """
    text = request.lower()

    # Check agent signals first — they override template matches
    for signal in _AGENT_SIGNALS:
        if re.search(signal, text):
            logger.debug("Agent signal '%s' matched in request", signal)
            return IntentResult(
                type="agent",
                template=None,
                confidence=0.85,
                reason=f"Agent signal detected: '{signal}'",
            )

    # Check template patterns
    for template_name, patterns in _TEMPLATE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                logger.debug("Template '%s' matched pattern '%s'", template_name, pattern)
                return IntentResult(
                    type="skill",
                    template=template_name,
                    confidence=0.80,
                    reason=f"Matched template '{template_name}' via pattern '{pattern}'",
                )

    # Default: skill is the safer choice
    logger.debug("No pattern matched — defaulting to skill")
    return IntentResult(
        type="skill",
        template=None,
        confidence=0.50,
        reason="No specific pattern matched; defaulting to skill (safer choice)",
    )
