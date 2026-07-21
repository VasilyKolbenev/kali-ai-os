"""Agent generator — uses any configured LLM (OpenAI/Anthropic/local) to produce agent.py."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from kernel.builder.safety_gate import check_code
from kernel.model_registry import cheap_model

logger = logging.getLogger(__name__)

# OPUS-301: load-bearing anthropic fallback — the registry SoT cheap model, not
# a literal. Changing config/model_registry.json 'cheap' moves this in lockstep.
_ANTHROPIC_FALLBACK_MODEL = cheap_model("anthropic")

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
    """Remove markdown code fences from LLM output."""
    text = re.sub(r"^```(?:python)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text.strip())
    return text.strip()


def _detect_provider() -> tuple[str, str] | None:
    """Detect which LLM provider has a valid API key.

    Priority: configured cloud_provider first, then any with a key.

    Returns:
        (provider_name, model_name) tuple, or None if none available.
    """
    # Read preferred provider from env (set by ConfigManager)
    preferred = os.environ.get("LLM_PROVIDER", "").lower()

    providers = [
        ("openai", "OPENAI_API_KEY", os.environ.get("OPENAI_MODEL", "gpt-4o-mini")),
        ("anthropic", "ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_MODEL", _ANTHROPIC_FALLBACK_MODEL)),
        ("google", "GOOGLE_API_KEY", os.environ.get("GOOGLE_MODEL", "gemini-2.0-flash")),
        ("deepseek", "DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")),
    ]

    # Try preferred first
    for name, key_var, model in providers:
        if name == preferred and os.environ.get(key_var, "").strip():
            return (name, model)

    # Fallback: any available
    for name, key_var, model in providers:
        if os.environ.get(key_var, "").strip():
            return (name, model)

    return None


def _call_llm(provider: str, model: str, system: str, user: str) -> str:
    """Call the specified LLM provider and return raw text response."""
    if provider == "openai":
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text  # type: ignore[index,union-attr]

    if provider == "google":
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        gmodel = genai.GenerativeModel(model, system_instruction=system)
        resp = gmodel.generate_content(user)
        return resp.text or ""

    if provider == "deepseek":
        import openai
        client = openai.OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com/v1",
        )
        resp = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""

    raise ValueError(f"Unsupported provider: {provider}")


def generate_agent(
    name: str,
    description: str,
    tools: list[dict[str, Any]],
    apis: list[str],
    agents_dir: Path,
) -> Path | None:
    """Generate an agent using the configured LLM provider.

    Detects available API keys and uses the user's preferred provider.
    Supports: OpenAI, Anthropic, Google, DeepSeek.

    Args:
        name: Kebab-case agent identifier.
        description: What the agent should do, in natural language.
        tools: List of tool dicts with "name" and "description" keys.
        apis: List of external API/service names the agent may call.
        agents_dir: Base directory; agent placed in ``{name}/``.

    Returns:
        Path to the created agent directory, or None on failure.
    """
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid agent name: {name}")

    provider_info = _detect_provider()
    if provider_info is None:
        logger.warning(
            "No LLM API key configured — agent generation unavailable. "
            "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, or DEEPSEEK_API_KEY."
        )
        return None

    provider, model = provider_info
    logger.info("Using %s (%s) for agent generation", provider, model)

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
        raw_code = _call_llm(provider, model, _SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        logger.error("%s API call failed: %s", provider, exc)
        return None

    agent_code = _strip_fences(raw_code)

    safety = check_code(agent_code)
    if not safety.safe:
        logger.warning("Generated unsafe code for '%s': %s", name, safety.issues)
        return None

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
        "generated_by": f"agent_generator/{provider}",
    }
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    logger.info("Agent '%s' generated via %s at %s", name, provider, agent_dir)
    return agent_dir
