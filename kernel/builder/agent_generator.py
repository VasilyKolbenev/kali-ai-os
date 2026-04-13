"""Agent generator — uses Claude API to produce agent.py + manifest.yaml."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from kernel.builder.safety_gate import check_code

logger = logging.getLogger(__name__)

# Import anthropic at module level so tests can patch it cleanly.
# The actual API key check happens at call time.
try:
    import anthropic  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

_SYSTEM_PROMPT = """\
You are an expert Python developer generating KALI agent code.

Rules — you MUST follow all of them:
1. Produce a single Python file that defines a class named `CustomAgent(BaseAgent)`.
2. Import BaseAgent with:
   from agents._base.agent_base import BaseAgent
3. Implement `get_name(self) -> str` returning the agent name as a string literal.
4. Implement `handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]`
   with if/elif branches for each tool, raising ValueError for unknown actions.
5. Use type hints on every function signature.
6. Use logging (import logging; logger = logging.getLogger(__name__)) — no print().
7. NEVER import: subprocess, importlib, ctypes, multiprocessing, shutil, signal,
   socket (unless explicitly required by the tools list), threading.
8. NEVER use: eval, exec, compile, __import__, getattr, setattr, delattr.
9. Add a `if __name__ == "__main__": CustomAgent().run()` guard at the bottom.
10. Return ONLY raw Python code — no markdown fences, no explanations.
"""


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output.

    Args:
        text: Raw text that may contain ```python ... ``` fences.

    Returns:
        Source code with fences stripped and leading/trailing whitespace removed.
    """
    # Remove opening fence (```python or ```)
    text = re.sub(r"^```(?:python)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\n?```\s*$", "", text.strip())
    return text.strip()


def generate_agent(
    name: str,
    description: str,
    tools: list[dict[str, Any]],
    apis: list[str],
    agents_dir: Path,
) -> Path | None:
    """Generate an agent using Claude API and write it to agents/{name}/.

    Calls the Anthropic Messages API with a constrained system prompt to
    produce a BaseAgent subclass. Writes ``agent.py`` and ``manifest.yaml``
    into ``agents_dir / name /``.

    Args:
        name: Kebab-case agent identifier (e.g. "crypto-watcher").
        description: What the agent should do, in natural language.
        tools: List of tool dicts with "name" and "description" keys.
        apis: List of external API/service names the agent may call.
        agents_dir: Base directory; the agent will be placed in ``{name}/``.

    Returns:
        Path to the created agent directory, or None on failure (missing API
        key, network error, or unexpected API response).
    """
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid agent name: {name}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping LLM agent generation")
        return None

    if anthropic is None:
        logger.error("anthropic package not installed")
        return None

    tools_description = "\n".join(
        f"- {t['name']}: {t.get('description', '')}" for t in tools
    )
    apis_description = ", ".join(apis) if apis else "none"

    user_prompt = (
        f"Agent name: {name}\n"
        f"Description: {description}\n"
        f"Tools to implement:\n{tools_description}\n"
        f"External APIs/services: {apis_description}\n\n"
        "Generate the complete agent.py file now."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_code = message.content[0].text  # type: ignore[index]
    except Exception as exc:
        logger.error("Claude API call failed: %s", exc)
        return None

    agent_code = _strip_fences(raw_code)

    # Safety gate: never write code that fails static analysis
    safety = check_code(agent_code)
    if not safety.safe:
        logger.warning("Generated unsafe code for '%s': %s", name, safety.issues)
        return None

    # Write files
    agent_dir = agents_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    (agent_dir / "agent.py").write_text(agent_code, encoding="utf-8")

    capabilities = [f"{name}.{t['name']}" for t in tools]
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "capabilities": capabilities,
        "tools": tools,
        "protocol": "native",
        "permissions": ["network"] if apis else [],
        "generated_by": "agent_generator_v2",
    }
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    logger.info("Agent '%s' generated by Claude at %s", name, agent_dir)
    return agent_dir
