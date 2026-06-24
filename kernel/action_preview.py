"""Action -> plain-language preview bridge (dry-run preview v1).

Turns a runtime dispatch ``(agent, action, args)`` into a user-facing
disclosure: a plain-language Russian label plus a risk tier, reusing the
consent capability risk classification (token-based, so it works on action
names too). DISCLOSURE ONLY — it does not gate or change execution.
"""

from __future__ import annotations

from typing import Any

from kernel.capabilities import classify_risk

# Plain-language RU labels for known runtime actions. Unknown actions fall back
# to the raw action name (still shown), with risk derived from the token rules.
_ACTION_LABELS: dict[str, str] = {
    "send_email": "Отправит письмо от твоего имени",
    "read_email": "Прочитает твою почту",
    "search_email": "Будет искать в твоей почте",
    "create_event": "Создаст событие в календаре от твоего имени",
    "delete_event": "Удалит событие из календаря",
    "get_events": "Посмотрит события в календаре",
    "send_message": "Отправит сообщение от твоего имени",
    "read_messages": "Прочитает твои сообщения",
    "get_weather": "Узнает погоду",
    "get_summary": "Соберёт сводку",
    "convert_currency": "Конвертирует валюту",
    "get_rates": "Узнает курсы валют",
}


def describe_action(
    agent: str, action: str, args: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Describe a dispatch as a plain-language, risk-tagged preview.

    Args:
        agent: The agent doing the action.
        action: The runtime action being dispatched (e.g. ``send_email``).
        args: Optional action arguments (reserved for richer future labels).

    Returns:
        ``{"agent", "action", "label", "risk"}`` — ``label`` is a plain RU
        description (or the raw action name if unknown) and ``risk`` is the
        token-based tier (``high`` / ``med`` / ``low``).
    """
    del args  # reserved for richer v2 labels; v1 labels are action-based
    return {
        "agent": agent,
        "action": action,
        "label": _ACTION_LABELS.get(action, action),
        "risk": classify_risk(action),
    }
