"""Agent plugin registry — discovers and manages agent manifests."""

import logging
from pathlib import Path
from typing import Any

import yaml

from kernel.models import AgentManifest

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Discovers agent manifests in a directory and provides lookup APIs.

    Each agent lives in its own subdirectory with a manifest.yaml.
    Tools from manifests are namespaced as '{agent_name}__{tool_name}'.
    """

    def __init__(self, agents_dir: Path) -> None:
        self._agents_dir = agents_dir
        self._agents: dict[str, AgentManifest] = {}

    def discover(self) -> list[AgentManifest]:
        """Scan agents directory for manifest.yaml files and register them."""
        self._agents.clear()

        if not self._agents_dir.exists():
            logger.warning("Agents directory not found: %s", self._agents_dir)
            return []

        for agent_dir in sorted(self._agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            manifest_path = agent_dir / "manifest.yaml"
            if not manifest_path.exists():
                continue

            try:
                raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                manifest = AgentManifest(**raw)
                self._agents[manifest.name] = manifest
                logger.info("Registered agent: %s v%s", manifest.name, manifest.version)
            except Exception:
                logger.exception("Failed to load manifest from %s", manifest_path)

        return list(self._agents.values())

    def get(self, name: str) -> AgentManifest | None:
        """Get agent manifest by name."""
        return self._agents.get(name)

    def list_registered(self) -> list[AgentManifest]:
        """List all registered agent manifests."""
        return list(self._agents.values())

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all agent tools formatted for LLM function calling."""
        tools: list[dict[str, Any]] = []
        for agent in self._agents.values():
            for tool in agent.tools:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{agent.name}__{tool.name}",
                            "description": tool.description,
                            "parameters": {
                                "type": "object",
                                "properties": tool.parameters,
                            },
                        },
                    }
                )
        return tools

    def find_agent_for_tool(self, tool_name: str) -> AgentManifest | None:
        """Find which agent owns a namespaced tool name."""
        if "__" not in tool_name:
            return None
        agent_name = tool_name.split("__")[0]
        return self._agents.get(agent_name)

    def list_skills(self) -> list[AgentManifest]:
        """Return only manifests with protocol='skill'."""
        return [m for m in self._agents.values() if m.protocol == "skill"]

    def list_agents_only(self) -> list[AgentManifest]:
        """Return only manifests with protocol!='skill'."""
        return [m for m in self._agents.values() if m.protocol != "skill"]
