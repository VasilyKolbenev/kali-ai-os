"""Install packages from .kali-agent files."""

import logging
import shutil
from pathlib import Path
from typing import Any

from kernel.catalog.package import get_package_info, unpack

logger = logging.getLogger(__name__)


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
        agent_dir = unpack(package_path, agents_dir / name)
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
