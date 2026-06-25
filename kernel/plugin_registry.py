"""Agent plugin registry — discovers and manages agent manifests.

Dual-format support (Agent Skills spec adoption, 2026-04):
- SKILL.md (new format, Agent Skills spec, https://agentskills.io)
- manifest.yaml (legacy KALI format, supported during migration)

When both exist in the same directory, SKILL.md takes precedence but legacy
manifest.yaml is consulted for tool definitions (for backward compatibility
with existing agent.py scripts).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from kernel.models import AgentManifest, AgentToolDef
from kernel.skills.loader import SkillManifest, load_skill
from kernel.skills.validator import ValidationError

logger = logging.getLogger(__name__)


def _skill_manifest_to_agent_manifest(
    skill: SkillManifest,
    legacy_manifest: AgentManifest | None = None,
) -> AgentManifest:
    """Build an AgentManifest from a SKILL.md-based skill.

    Args:
        skill: Parsed SKILL.md.
        legacy_manifest: Optional legacy manifest.yaml (for tool definitions).

    Returns:
        AgentManifest suitable for the existing runtime.
    """
    # Version — prefer metadata, fall back to legacy, else 1.0.0
    version = str(skill.metadata.get("version", "") or "")
    if not version and legacy_manifest:
        version = legacy_manifest.version
    if not version:
        version = "1.0.0"

    # Tools — legacy manifest gives us parameter schemas, SKILL.md only has names
    if legacy_manifest and legacy_manifest.tools:
        tools = legacy_manifest.tools
    else:
        # Derive minimal tool defs from allowed-tools frontmatter field
        tools = [
            AgentToolDef(name=name, description=f"Tool {name} from skill {skill.name}")
            for name in skill.tool_list
        ]

    capabilities = list(legacy_manifest.capabilities) if legacy_manifest else []
    if not capabilities and skill.metadata.get("capabilities"):
        caps = skill.metadata["capabilities"]
        if isinstance(caps, list):
            capabilities = [str(c) for c in caps]
        elif isinstance(caps, str):
            capabilities = [caps]

    # Protocol — if skill has scripts/agent.py, treat as legacy "native"
    # (in-process protocol will dispatch). Otherwise "skill" — pure Markdown skill.
    has_script_impl = skill.has_scripts and (skill.scripts_dir / "agent.py").is_file()
    protocol = legacy_manifest.protocol if legacy_manifest else (
        "native" if has_script_impl else "skill"
    )

    # Permissions — reuse legacy if available, else infer from compatibility hints
    if legacy_manifest:
        permissions = legacy_manifest.permissions
    else:
        perm_names: list[str] = []
        compat = (skill.compatibility or "").lower()
        if "network" in compat:
            perm_names.append("network")
        if "storage" in compat or "file" in compat:
            perm_names.append("storage")
        # Use the backward-compat list form that AgentManifest accepts
        permissions = perm_names  # type: ignore[assignment]

    return AgentManifest(
        name=skill.name,
        version=version,
        description=skill.description,
        capabilities=capabilities,
        tools=tools,
        protocol=protocol,
        permissions=permissions,  # type: ignore[arg-type]
    )


class PluginRegistry:
    """Discovers agent/skill manifests in a directory and provides lookup APIs.

    Each agent lives in its own subdirectory containing SKILL.md (preferred)
    or manifest.yaml (legacy). Tools are namespaced as '{agent_name}__{tool_name}'.
    """

    def __init__(self, agents_dir: Path) -> None:
        self._agents_dir = agents_dir
        self._agents: dict[str, AgentManifest] = {}
        # Keep the underlying SKILL.md for new-format skills (needed for runtime).
        self._skills: dict[str, SkillManifest] = {}

    @property
    def agents_dir(self) -> Path:
        return self._agents_dir

    def _load_legacy_manifest(self, path: Path) -> AgentManifest | None:
        """Parse a legacy manifest.yaml. Returns None on error."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                logger.warning("manifest.yaml must be a mapping: %s", path)
                return None
            return AgentManifest(**raw)
        except Exception:
            logger.exception("Failed to parse legacy manifest: %s", path)
            return None

    def _load_skill(self, agent_dir: Path) -> SkillManifest | None:
        """Parse a SKILL.md file. Returns None on error."""
        try:
            return load_skill(agent_dir, source="builtin", strict=False)
        except (FileNotFoundError, ValidationError):
            return None
        except Exception:
            logger.exception("Failed to parse SKILL.md: %s", agent_dir)
            return None

    def discover(self) -> list[AgentManifest]:
        """Scan agents directory for SKILL.md (preferred) or manifest.yaml files.

        Discovery rules:
        1. SKILL.md + manifest.yaml both present → merge (SKILL.md metadata wins,
           legacy manifest contributes tool definitions)
        2. SKILL.md only → pure skill, derive minimal AgentManifest
        3. manifest.yaml only → legacy path, unchanged behaviour
        4. Neither → skip directory
        """
        self._agents.clear()
        self._skills.clear()

        if not self._agents_dir.exists():
            logger.warning("Agents directory not found: %s", self._agents_dir)
            return []

        skill_count = 0
        legacy_count = 0

        for agent_dir in sorted(self._agents_dir.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name.startswith(("_", ".")):
                continue

            skill = self._load_skill(agent_dir)
            legacy_path = agent_dir / "manifest.yaml"
            legacy = (
                self._load_legacy_manifest(legacy_path)
                if legacy_path.is_file()
                else None
            )

            if skill is None and legacy is None:
                continue  # not a valid skill/agent directory

            if skill is not None:
                manifest = _skill_manifest_to_agent_manifest(skill, legacy)
                self._skills[manifest.name] = skill
                skill_count += 1
                source = "SKILL.md + legacy" if legacy else "SKILL.md"
            else:
                manifest = legacy  # type: ignore[assignment]
                legacy_count += 1
                source = "manifest.yaml (legacy)"

            self._agents[manifest.name] = manifest
            logger.info(
                "Registered: %s v%s [%s]", manifest.name, manifest.version, source
            )

        logger.info(
            "Plugin registry: %d skills (SKILL.md) + %d legacy agents = %d total",
            skill_count, legacy_count, len(self._agents),
        )
        return list(self._agents.values())

    def register_dir(self, agent_dir: Path) -> AgentManifest | None:
        """Register a single agent/skill directory into the live registry.

        Used right after the builder deploys a new skill so it becomes callable
        immediately — its tools enter the LLM tool palette and it appears in
        GET /agents — WITHOUT a full :meth:`discover`. A full re-scan rebuilds
        every manifest and would disturb the in-memory consent/approval state of
        the other agents (M2.2). Mirrors one iteration of :meth:`discover`.

        Returns the registered manifest, or None if the directory is not a valid
        skill/agent (so callers can detect a no-op).
        """
        if not agent_dir.is_dir() or agent_dir.name.startswith(("_", ".")):
            return None
        skill = self._load_skill(agent_dir)
        legacy_path = agent_dir / "manifest.yaml"
        legacy = (
            self._load_legacy_manifest(legacy_path) if legacy_path.is_file() else None
        )
        if skill is None and legacy is None:
            return None
        if skill is not None:
            manifest = _skill_manifest_to_agent_manifest(skill, legacy)
            self._skills[manifest.name] = skill
        else:
            manifest = legacy  # type: ignore[assignment]
        self._agents[manifest.name] = manifest
        logger.info("Registered (incremental): %s v%s", manifest.name, manifest.version)
        return manifest

    def get(self, name: str) -> AgentManifest | None:
        """Get agent manifest by name."""
        return self._agents.get(name)

    def get_skill(self, name: str) -> SkillManifest | None:
        """Get underlying SKILL.md manifest for a registered skill.

        Returns None for legacy manifest.yaml-only agents.
        """
        return self._skills.get(name)

    def list_registered(self) -> list[AgentManifest]:
        """List all registered agent manifests."""
        return list(self._agents.values())

    def list_skills(self) -> list[AgentManifest]:
        """Return manifests declared as protocol='skill' (pure SKILL.md, no scripts)."""
        return [m for m in self._agents.values() if m.protocol == "skill"]

    def list_agents_only(self) -> list[AgentManifest]:
        """Return manifests that are not pure skills (have executable code)."""
        return [m for m in self._agents.values() if m.protocol != "skill"]

    def _is_callable(self, agent: AgentManifest) -> bool:
        """Whether the agent's tools can actually be dispatched at runtime.

        Native/manifest.yaml agents dispatch through agent_runtime. Pure
        SKILL.md skills (protocol="skill") are only executable when a
        ``skill.yaml`` template backs them (SkillExecutor.load_skill); without
        one, invoking the tool yields "Skill not found", so it must not be
        advertised to the LLM in the first place.
        """
        if agent.protocol != "skill":
            return True
        return (self._agents_dir / agent.name / "skill.yaml").is_file()

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all agent tools formatted for LLM function calling (OpenAI/Anthropic)."""
        tools: list[dict[str, Any]] = []
        for agent in self._agents.values():
            if not self._is_callable(agent):
                continue
            for tool in agent.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{agent.name}__{tool.name}",
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": tool.parameters,
                        },
                    },
                })
        # Built-in tool so the assistant can list the user's own agents/skills —
        # otherwise "what agents do I have" misroutes to whatever list-like tool
        # exists. Executed in kernel/tool_dispatch.execute_tool_call.
        from kernel.tool_dispatch import LIST_AGENTS_TOOL

        tools.append(LIST_AGENTS_TOOL)
        return tools

    def find_agent_for_tool(self, tool_name: str) -> AgentManifest | None:
        """Find which agent owns a namespaced tool name (format: agent__tool)."""
        if "__" not in tool_name:
            return None
        agent_name = tool_name.split("__", 1)[0]
        return self._agents.get(agent_name)
