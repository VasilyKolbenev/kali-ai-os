"""Capability taxonomy — plain-language RU disclosure for agent permissions.

Pure, agent-name-agnostic classification of manifest ``capabilities`` ids into
a user-facing disclosure shape. Used by the consent-disclosure flow (Store
enable) to tell a non-tech user, in plain Russian, what an agent will be able
to do before they turn it on. This is DISCLOSURE ONLY — it does not enforce or
change any permission behavior.

Risk rules (classification is purely from the capability id, never the agent
name):
  - "high": side-effecting on personal data — id contains a ``write``, ``send``,
    ``create`` or ``delete`` action token. Labels use «…от твоего имени».
  - "med":  personal-data reads — id contains a ``read`` token.
  - "low":  everything else (network/storage, public lookups, search).

An agent is ``sensitive`` iff ANY capability is "high" or "med", so weather /
currency style agents (only public lookups, network or storage) stay
non-sensitive and keep the one-click enable.
"""

from typing import Literal

Risk = Literal["low", "med", "high"]

# Action tokens that make a capability side-effecting on personal data → high.
_HIGH_TOKENS = ("write", "send", "create", "delete")
# Token marking a personal-data read → med.
_READ_TOKEN = "read"

# Plain-language RU labels for the real capability ids the shipped manifests
# use. Keys are exact capability ids. Anything not listed falls back to the id
# itself at risk "low" (see ``_describe_one``).
_LABELS: dict[str, str] = {
    # email
    "email.read": "Читать твою почту",
    "email.send": "Отправлять письма от твоего имени",
    "email.search": "Искать письма в почте",
    # calendar
    "calendar.read": "Смотреть события в календаре",
    "calendar.write": "Создавать и менять события в календаре от твоего имени",
    # messenger / telegram
    "messenger.read": "Читать твои сообщения",
    "messenger.send": "Отправлять сообщения от твоего имени",
    "telegram.send": "Отправлять сообщения в Telegram от твоего имени",
    "telegram.notify": "Присылать тебе уведомления в Telegram",
    # tasks / todoist
    "tasks.read": "Смотреть твои задачи",
    "tasks.write": "Создавать и менять задачи от твоего имени",
    "todoist.read": "Смотреть твои задачи в Todoist",
    "todoist.write": "Создавать и менять задачи в Todoist от твоего имени",
    # notion
    "notion.search": "Искать в твоём Notion",
    "notion.read": "Читать страницы в твоём Notion",
    "notion.write": "Создавать и менять страницы в Notion от твоего имени",
    # life-dashboard
    "dashboard.read": "Смотреть данные твоей панели",
    "dashboard.write": "Менять данные твоей панели от твоего имени",
    # github
    "github.repos": "Смотреть твои репозитории на GitHub",
    "github.issues": "Смотреть задачи (issues) на GitHub",
    "github.prs": "Смотреть pull request'ы на GitHub",
    # public lookups — low risk
    "weather.current": "Узнавать текущую погоду",
    "weather.forecast": "Смотреть прогноз погоды",
    "currency.rates": "Узнавать курсы валют",
    "currency.convert": "Конвертировать суммы между валютами",
    "news.headlines": "Показывать новостные заголовки",
    "news.search": "Искать новости",
    # coding — local helpers, low risk
    "coding.review": "Делать ревью кода",
    "coding.generate": "Генерировать код",
    "coding.explain": "Объяснять код",
    # smart-home
    "smarthome.lights": "Управлять освещением",
    "smarthome.climate": "Управлять климатом дома",
    "smarthome.devices": "Управлять устройствами умного дома",
    # system / misc
    "system.info": "Смотреть информацию о системе",
    "system.timer": "Ставить таймеры",
    "canvas.render": "Рисовать на холсте",
    "canvas.clear": "Очищать холст",
}


def _classify(cap: str) -> Risk:
    """Classify a single capability id into a risk tier.

    Matching is on action tokens inside the id (split on ``.`` or ``:``) plus a
    substring check, so it works for both dotted (``calendar.write``) and
    colon (``calendar:write``) id styles.

    Args:
        cap: A capability id, e.g. ``"email.send"`` or ``"calendar.read"``.

    Returns:
        ``"high"``, ``"med"`` or ``"low"`` per the module risk rules.
    """
    lowered = cap.lower()
    parts = lowered.replace(":", ".").split(".")
    if any(tok in parts for tok in _HIGH_TOKENS) or any(
        tok in lowered for tok in ("delete", "create")
    ):
        return "high"
    if _READ_TOKEN in parts:
        return "med"
    return "low"


def classify_risk(token_source: str) -> Risk:
    """Token-based risk tier for a capability id or a runtime action name.

    Both capability ids (``email.send``) and action names (``send_email``)
    encode the action as tokens, so the same rules apply: write/send/create/
    delete -> ``high``, read -> ``med``, else ``low``. Used by consent
    disclosure and the dry-run action preview.

    Action names use underscores (``send_email``) while capability ids use dots
    (``email.send``); normalize underscores to dots so the token split treats
    both styles uniformly.
    """
    return _classify(token_source.replace("_", "."))


def _describe_one(cap: str) -> dict[str, str]:
    """Build the disclosure entry for one capability id.

    Args:
        cap: A capability id from the agent manifest.

    Returns:
        A dict ``{"id", "label", "risk"}``. Unknown ids fall back to the id
        itself as the label at risk ``"low"``.
    """
    return {"id": cap, "label": _LABELS.get(cap, cap), "risk": _classify(cap)}


def describe_capabilities(caps: list[str]) -> dict:
    """Describe a manifest's capabilities for plain-language consent disclosure.

    Pure function: classification depends only on the capability ids, never on
    the agent name.

    Args:
        caps: The agent manifest's ``capabilities`` list of ids.

    Returns:
        A dict with the disclosure contract shape::

            {
              "capabilities": [{"id": str, "label": str, "risk": str}, ...],
              "sensitive": bool,
            }

        where ``sensitive`` is ``True`` iff any capability is risk ``"high"``
        or ``"med"`` (personal-data access). Agents with only public lookups,
        network or storage stay non-sensitive (one-click enable).
    """
    described = [_describe_one(c) for c in caps]
    sensitive = any(c["risk"] in ("high", "med") for c in described)
    return {"capabilities": described, "sensitive": sensitive}
