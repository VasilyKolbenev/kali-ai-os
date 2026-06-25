"""Shared LLM tool-call dispatch.

Chat and the voice pipelines each had their own copy of "what to do when the
model returns a tool call" — and the voice copies only *announced* the call
(published an ``agent.response`` event) without executing it, so spoken
commands silently did nothing. This module is the single execution path all
three use, so they cannot diverge again.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kernel.llm_router import LLMRequest, LLMRouter, ToolCall

logger = logging.getLogger(__name__)


LIST_AGENTS_TOOL_NAME = "kali__list_my_agents"

#: Built-in palette tool — the assistant's only way to answer "what agents /
#: skills do I have". Without it such queries misroute to whatever list-like
#: tool exists (e.g. the tasks agent). Appended to the palette in
#: ``PluginRegistry.get_all_tools``; executed in :func:`execute_tool_call`.
LIST_AGENTS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LIST_AGENTS_TOOL_NAME,
        "description": (
            "List the user's own agents and skills — their names, what each does, "
            "and whether each is running. Use whenever the user asks what agents or "
            "skills they have or created, e.g. 'какие у меня агенты', 'покажи моих "
            "помощников', 'проверь моих агентов', 'what agents do I have'. This lists "
            "the agents themselves, NOT their tasks or to-dos."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def _build_my_agents(state: Any) -> dict[str, Any]:
    """Enumerate the user's registered agents/skills with their running status."""
    registry = state.plugin_registry
    runtime = getattr(state, "agent_runtime", None)
    running: set[str] = set()
    if runtime is not None:
        try:
            running = {a["name"] for a in runtime.list_agents()}
        except Exception:
            running = set()
    agents = [
        {"name": m.name, "description": m.description, "running": m.name in running}
        for m in registry.list_registered()
    ]
    return {"agents": agents, "count": len(agents)}


async def execute_tool_call(
    state: Any,
    router: LLMRouter,
    call: ToolCall,
    context: list[dict[str, Any]],
    user_text: str,
) -> tuple[str, dict[str, Any], str] | None:
    """Execute one LLM tool call and return ``(text, raw_result, source)``.

    Skills route through ``skill_executor``; native agents through
    ``agent_runtime``, auto-loading one that isn't running yet — first use of a
    non-eager agent on a clean install would otherwise raise "not loaded". A
    second LLM pass phrases the raw result naturally for the user.

    Args:
        state: The app state (provides ``plugin_registry``, ``skill_executor``,
            ``agent_runtime``).
        router: LLM router used for the natural-language second pass.
        call: The tool call the model emitted.
        context: Prior conversation turns for the second-pass prompt.
        user_text: The user's original message, for the second-pass prompt.

    Returns:
        ``(text, raw_result, source)`` where ``source`` is ``"agent-<name>"``,
        or ``None`` if ``call.name`` is not an ``agent__action`` tool (so the
        caller can fall back to the plain text reply).
    """
    if call.name == LIST_AGENTS_TOOL_NAME:
        result = _build_my_agents(state)
        source = "agent-kali"
    elif "__" in call.name:
        agent_name, action = call.name.split("__", 1)
        manifest = state.plugin_registry.get(agent_name)
        if manifest is not None and manifest.protocol == "skill":
            result = await state.skill_executor.execute(agent_name, action, call.arguments)
        else:
            # Idempotent: loads the agent if it isn't running yet, no-ops otherwise.
            try:
                await state.agent_runtime.load_agent(agent_name)
            except Exception:
                logger.debug("Auto-load of '%s' failed; dispatch will surface it", agent_name)
            result = await state.agent_runtime.dispatch(agent_name, action, call.arguments)
        source = f"agent-{agent_name}"
    else:
        return None

    tool_context = list(context)
    tool_context.append({"role": "user", "content": user_text})
    system_msg = (
        f"Tool {call.name} returned:\n"
        f"{json.dumps(result, ensure_ascii=False)}\n"
        "Please summarize this naturally for the user."
    )
    formatted = await router.route(
        LLMRequest(text=system_msg, context=tool_context, available_tools=[])
    )
    return formatted.text, result, source
