"""Deployer — writes generated files and registers in kernel."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def deploy_skill(
    skill_dir: Path,
    skill_executor: Any,
    scheduler: Any | None = None,
) -> dict[str, Any]:
    """Deploy a generated skill into the running system.

    Args:
        skill_dir: Path to skill directory (must contain skill.yaml)
        skill_executor: SkillExecutor instance to load skill into
        scheduler: Optional Scheduler for cron registration

    Returns:
        {"status": "deployed", "name": str} or {"status": "error", "message": str}
    """
    name = skill_dir.name
    try:
        skill_executor.load_skill(skill_dir)
    except Exception as e:
        logger.exception("Failed to deploy skill '%s'", name)
        return {"status": "error", "message": str(e)}

    # Register cron if skill has reminders/schedule
    if scheduler:
        info = skill_executor.get_skill_info(name)
        if info:
            config = info.get("config", {})
            cron = None
            reminders = config.get("reminders", {})
            if reminders.get("enabled"):
                interval_h = reminders.get("interval_hours")
                if interval_h:
                    cron = f"0 */{interval_h} * * *"
            schedule = config.get("schedule", {})
            if schedule.get("cron"):
                cron = schedule["cron"]
            if cron:
                try:
                    scheduler.register_cron(name, cron, topic=f"skill.{name}.trigger")
                except ValueError as e:
                    logger.warning("Invalid cron for skill '%s': %s", name, e)

    logger.info("Deployed skill: %s", name)
    return {"status": "deployed", "name": name}


async def deploy_agent(
    agent_dir: Path,
    plugin_registry: Any,
    agent_runtime: Any,
) -> dict[str, Any]:
    """Deploy a generated agent into the running system.

    Args:
        agent_dir: Path to agent directory (must contain manifest.yaml + agent.py)
        plugin_registry: PluginRegistry to re-discover agents
        agent_runtime: AgentRuntime to load agent

    Returns:
        {"status": "deployed", "name": str} or {"status": "error", "message": str}
    """
    name = agent_dir.name
    try:
        plugin_registry.discover()
        manifest = plugin_registry.get(name)
        if not manifest:
            return {"status": "error", "message": f"Manifest not found for '{name}'"}
        await agent_runtime.load_agent(name)
    except Exception as e:
        import shutil

        logger.exception("Failed to deploy agent '%s'", name)
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        return {"status": "error", "message": str(e)}

    logger.info("Deployed agent: %s", name)
    return {"status": "deployed", "name": name}
