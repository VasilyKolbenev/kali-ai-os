"""Coding agent — code assistance stub. Real LLM integration in v2."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class CodingAgent(BaseAgent):
    """Stub agent returning placeholder responses. Real Claude integration in v2."""

    def get_name(self) -> str:
        return "coding"

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
            lines = len(code.strip().split("\n")) if code else 0
            return {
                "explanation": (
                    f"This is {language} code with {lines} lines. "
                    "Detailed explanation requires LLM integration (v2)."
                ),
                "language": language,
                "lines": lines,
            }

        elif action == "review_code":
            return {
                "review": "Code review requires LLM integration (v2).",
                "issues": [],
                "score": "N/A",
            }

        elif action == "suggest_improvement":
            return {
                "suggestions": ["LLM-powered suggestions coming in v2."],
                "original_lines": len(code.strip().split("\n")) if code else 0,
            }

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    CodingAgent().run()
