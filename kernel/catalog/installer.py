"""Install packages from .kali-agent files."""

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

from kernel.catalog.package import get_package_info, unpack

logger = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _validate_agent_name(name: str, agents_dir: Path) -> Path:
    """Validate a manifest-supplied agent name and resolve its install path.

    The name comes from an untrusted package manifest, so it must be a single
    safe path component — never an absolute path, a parent traversal, or a
    drive/anchor — to prevent arbitrary file writes outside ``agents_dir``.

    Args:
        name: Agent name read from the package manifest.
        agents_dir: Base directory under which the agent is installed.

    Returns:
        The resolved install directory (``agents_dir / name``).

    Raises:
        ValueError: If the name is unsafe or escapes ``agents_dir``.
    """
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid agent name: {name}")
    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive or candidate.anchor:
        raise ValueError(f"Invalid agent name: {name}")
    if not _NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid agent name: {name}")

    target = (agents_dir / name).resolve()
    base = agents_dir.resolve()
    if os.path.commonpath([str(target), str(base)]) != str(base):
        raise ValueError(f"Agent name escapes install directory: {name}")
    return target


async def install_package(
    package_path: Path,
    agents_dir: Path,
    skill_executor: Any | None = None,
    plugin_registry: Any | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    """Install a .kali-agent package.

    Steps: read manifest → unpack to named dir → safety check (agents only) → deploy.

    Args:
        package_path: Path to the .kali-agent file.
        agents_dir: Directory where agents/skills are installed.
        skill_executor: Optional SkillExecutor for skill deployment.
        plugin_registry: Optional PluginRegistry for agent deployment.
        agent_runtime: Optional AgentRuntime for agent deployment.

    Returns:
        Dict with ``status`` key and additional info depending on outcome.
    """
    try:
        info = get_package_info(package_path)
        name: str = info.get("name", package_path.stem)
        target_dir = _validate_agent_name(name, agents_dir)
        agent_dir = unpack(package_path, target_dir)
    except Exception as e:
        return {"status": "error", "message": f"Unpack failed: {e}"}

    # Safety check for agents with code
    code_path = agent_dir / "agent.py"
    if code_path.exists():
        from kernel.builder.safety_gate import check_code

        safety = check_code(code_path.read_text(encoding="utf-8"))
        if not safety.safe:
            shutil.rmtree(agent_dir)
            return {"status": "unsafe", "name": name, "issues": safety.issues}

    # Deploy skill
    skill_yaml = agent_dir / "skill.yaml"
    if skill_yaml.exists() and skill_executor:
        try:
            skill_executor.load_skill(agent_dir)
            return {"status": "installed", "name": name, "type": "skill"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Deploy agent
    if plugin_registry and agent_runtime:
        try:
            plugin_registry.discover()
            await agent_runtime.load_agent(name)
            return {"status": "installed", "name": name, "type": "agent"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "installed", "name": name, "type": "files_only"}
