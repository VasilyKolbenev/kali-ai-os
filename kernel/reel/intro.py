"""Build the short spoken intro line for an agent's share reel."""
import logging

from kernel.llm_router import LLMRequest

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Ты пишешь ОДНУ короткую дружелюбную фразу-представление голосового агента "
    "для рекламного ролика. Только одно предложение на русском, без кавычек, "
    "без эмодзи, не длиннее 15 слов."
)


def _template(name: str, description: str) -> str:
    """Deterministic fallback line used when the LLM is unavailable."""
    desc = description.strip().rstrip(".")
    return f"Привет! Я {name}. {desc}." if desc else f"Привет! Я {name}."


async def build_intro_line(name: str, description: str, router: object) -> str:
    """Return a one-sentence RU intro for the agent, in its voice.

    Uses a single non-streaming LLM call; on ANY failure or empty output,
    returns a deterministic template built from ``name``/``description``.
    Never raises, never returns empty.

    Args:
        name: Agent display/slug name.
        description: Agent description.
        router: An object exposing ``async route(LLMRequest) -> resp.text``.
    """
    prompt = (
        f"Представь голосового агента по имени «{name}». "
        f"Что он умеет: {description}. Напиши фразу-представление."
    )
    try:
        resp = await router.route(  # type: ignore[attr-defined]
            LLMRequest(text=prompt, context=[], available_tools=[], system_prompt=_SYSTEM)
        )
        text = (resp.text or "").strip().strip('"').strip()
        if text:
            return text
    except Exception:  # noqa: BLE001 — any provider error degrades to template
        logger.warning("reel intro LLM failed; using template", exc_info=True)
    return _template(name, description)
