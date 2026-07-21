"""Coding agent — code assistance with Claude API integration."""

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent

try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-5"
_MAX_TOKENS = 1024


class CodingAgent(BaseAgent):
    """Coding assistant with real Claude API integration. Falls back to placeholders if no API key."""

    def __init__(self) -> None:
        super().__init__()
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def get_name(self) -> str:
        return "coding"

    def _get_client(self) -> "Anthropic | None":
        """Return an Anthropic client if SDK is available and API key is set.

        Returns:
            Anthropic client instance, or None if unavailable.
        """
        if not _ANTHROPIC_AVAILABLE:
            logger.warning("anthropic package not installed — using placeholder responses")
            return None
        if not self._api_key:
            logger.warning("ANTHROPIC_API_KEY not set — using placeholder responses")
            return None
        return Anthropic(api_key=self._api_key)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle coding actions: explain_code, review_code, suggest_improvement.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown.
        """
        code = args.get("code", "")
        language = args.get("language", "unknown")

        if action == "explain_code":
            return self._explain_code(code, language)
        elif action == "review_code":
            return self._review_code(code, language)
        elif action == "suggest_improvement":
            return self._suggest_improvement(code, language)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _explain_code(self, code: str, language: str) -> dict[str, Any]:
        """Explain what a piece of code does.

        Args:
            code: Source code to explain.
            language: Programming language of the code.

        Returns:
            Dict with 'explanation' key.
        """
        client = self._get_client()
        if client is None:
            lines = len(code.strip().split("\n")) if code else 0
            return {
                "explanation": (
                    f"This is {language} code with {lines} lines. "
                    "Detailed explanation requires LLM integration (v2)."
                ),
                "language": language,
                "lines": lines,
            }

        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": f"Explain this {language} code concisely:\n\n```{language}\n{code}\n```",
                    }
                ],
            )
            return {"explanation": response.content[0].text}
        except Exception as exc:
            logger.error("explain_code API call failed: %s", exc)
            lines = len(code.strip().split("\n")) if code else 0
            return {
                "explanation": f"API error: {exc}",
                "language": language,
                "lines": lines,
            }

    def _review_code(self, code: str, language: str) -> dict[str, Any]:
        """Review code for bugs, style issues, and improvements.

        Args:
            code: Source code to review.
            language: Programming language of the code.

        Returns:
            Dict with 'review' and 'issues' keys.
        """
        client = self._get_client()
        if client is None:
            return {
                "review": "Code review requires LLM integration (v2).",
                "issues": [],
                "score": "N/A",
            }

        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Review this code for bugs, style, and improvements. Be concise:\n\n"
                            f"```{language or ''}\n{code}\n```"
                        ),
                    }
                ],
            )
            return {"review": response.content[0].text, "issues": []}
        except Exception as exc:
            logger.error("review_code API call failed: %s", exc)
            return {"review": f"API error: {exc}", "issues": []}

    def _suggest_improvement(self, code: str, language: str) -> dict[str, Any]:
        """Suggest improvements for code.

        Args:
            code: Source code to improve.
            language: Programming language of the code.

        Returns:
            Dict with 'suggestion' key.
        """
        client = self._get_client()
        if client is None:
            return {
                "suggestions": ["LLM-powered suggestions coming in v2."],
                "original_lines": len(code.strip().split("\n")) if code else 0,
            }

        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Suggest improvements for this code. "
                            f"Return improved version with explanation:\n\n"
                            f"```{language or ''}\n{code}\n```"
                        ),
                    }
                ],
            )
            return {"suggestion": response.content[0].text}
        except Exception as exc:
            logger.error("suggest_improvement API call failed: %s", exc)
            return {"suggestion": f"API error: {exc}"}


if __name__ == "__main__":
    CodingAgent().run()
