"""Tool call dispatcher — routes LLM tool calls to agents."""

import logging
from typing import Any

from kernel.agent_runtime.runtime import AgentRuntime
from kernel.plugin_registry import PluginRegistry

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches LLM tool calls to the correct agent.

    Tool names follow the format: {agent_name}__{tool_name}.
    Agents are auto-loaded on first dispatch if not already running.
    """

    def __init__(self, runtime: AgentRuntime, registry: PluginRegistry) -> None:
        self._runtime = runtime
        self._registry = registry

    def parse_tool_name(self, tool_name: str) -> tuple[str, str]:
        if "__" not in tool_name:
            raise ValueError(f"Invalid tool name format: {tool_name} (expected agent__action)")
        parts = tool_name.split("__", 1)
        return parts[0], parts[1]

    async def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        agent_name, action = self.parse_tool_name(tool_name)

        manifest = self._registry.get(agent_name)
        if manifest is None:
            raise ValueError(f"Agent '{agent_name}' not found in registry")

        if agent_name not in self._runtime._agents:
            logger.info("Auto-loading agent '%s' for tool call", agent_name)
            await self._runtime.load_agent(agent_name)

        return await self._runtime.dispatch(agent_name, action, arguments)
