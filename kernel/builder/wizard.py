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
        # Map answers to config based on question index
        config: dict[str, Any] = {}
        for i, (q, a) in enumerate(zip(self.questions, self.answers)):
            if "часто" in q or "interval" in q.lower():
                config["interval"] = a
            elif "цел" in q or "goal" in q.lower():
                config["goal"] = a
            elif "уведом" in q or "notify" in q.lower() or "куда" in q:
                config["notify_channel"] = a
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
        "Что конкретно должен делать агент?",
        "Какие внешние сервисы или API нужны?",
        "Как часто выполнять и куда отправлять результат?",
    ]


def _slugify(text: str) -> str:
    """Convert text to kebab-case slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:40].strip("-")
