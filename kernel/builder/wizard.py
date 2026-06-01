"""Voice wizard — guided conversation for skill/agent creation."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from kernel.builder.intent_classifier import IntentResult

logger = logging.getLogger(__name__)


@dataclass
class WizardSession:
    """Tracks state of a guided creation conversation."""

    request: str
    intent: IntentResult
    questions: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    _step: int = 0

    @property
    def is_complete(self) -> bool:
        return self._step >= len(self.questions)

    @property
    def current_question(self) -> str | None:
        if self._step < len(self.questions):
            return self.questions[self._step]
        return None

    def answer(self, text: str) -> str | None:
        """Record answer, return next question or None if done."""
        self.answers.append(text)
        self._step += 1
        return self.current_question

    def build_spec(self) -> dict[str, Any]:
        """Build structured spec from answers."""
        spec: dict[str, Any] = {
            "name": _slugify(self.request),
            "description": self.request,
            "type": self.intent.type,
            "template": self.intent.template,
        }
        config: dict[str, Any] = {}
        for i, (q, a) in enumerate(zip(self.questions, self.answers)):
            key = _question_to_key(q)
            if key:
                config[key] = a
            else:
                config[f"param_{i}"] = a
        spec["config"] = config
        return spec


def create_wizard(request: str, intent: IntentResult) -> WizardSession:
    """Create wizard session with appropriate questions.

    Args:
        request: Original user request string.
        intent: Classified intent result.

    Returns:
        WizardSession ready to guide the user through creation.
    """
    if intent.type == "skill":
        questions = _skill_questions(intent.template or "tracker")
    else:
        questions = _agent_questions()
    return WizardSession(request=request, intent=intent, questions=questions)


def _skill_questions(template: str) -> list[str]:
    """Generate questions for skill creation."""
    base: list[str] = []
    if template == "tracker":
        base = [
            "Какая дневная цель?",
            "Как часто напоминать?",
            "Куда отправлять уведомления — голосом или в телеграм?",
        ]
    elif template == "reminder":
        base = [
            "Как часто напоминать?",
            "В какое время начинать и заканчивать?",
        ]
    elif template == "monitor":
        base = [
            "Какой URL или сервис проверять?",
            "Как часто проверять?",
        ]
    elif template == "notifier":
        base = [
            "При каком условии уведомлять?",
            "Куда отправлять — голосом или в телеграм?",
        ]
    elif template == "logger":
        base = [
            "Какие события записывать?",
        ]
    return base


def _agent_questions() -> list[str]:
    """Generate questions for agent creation."""
    return [
        "Откуда мне лучше брать эти данные? (Если не знаете — ничего страшного, я постараюсь найти источник сам)",
        "Как часто нужно это выполнять и куда присылать результат?",
        "Есть ли какие-то особые условия? (Например, уведомлять только при падении цены)",
    ]


def _slugify(text: str) -> str:
    """Convert text to kebab-case slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:40].strip("-")


def _question_to_key(question: str) -> str:
    """Map a wizard question text to the config key its answer populates.

    Lowercases the question once so substring needles are case-insensitive
    (wizard questions start with capitalised words like "Куда" / "Какая").

    Order matters: `trigger` is checked BEFORE `notify_channel` because the
    notifier question "При каком условии уведомлять?" contains both "услов"
    and "уведом"; tighter / earlier matches win.

    Returns "" for unrecognised questions so they fall into the param_N
    bucket downstream (matching the historical `_build_spec` behaviour).
    """
    q = question.lower()
    if "часто" in q or "interval" in q:
        return "interval"
    elif "цел" in q or "goal" in q:
        return "goal"
    elif "услов" in q or "trigger" in q:
        return "trigger"
    elif "уведом" in q or "notify" in q or "куда" in q:
        return "notify_channel"
    elif "url" in q or "сервис" in q or "источник" in q or "откуда" in q:
        return "target"
    elif "событ" in q or "категор" in q:
        return "categories"
    elif "врем" in q or "time" in q:
        return "time_window"
    return ""
