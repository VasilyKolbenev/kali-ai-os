"""Deployer — writes generated files, registers in kernel, rolls back on failure."""

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _cleanup_dir(path: Path) -> None:
    """Safely remove a deployment directory on failure."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        logger.info("Rolled back: removed %s", path)
    except Exception as exc:
        logger.warning("Rollback cleanup failed for %s: %s", path, exc)


async def deploy_skill(
    skill_dir: Path,
    skill_executor: Any,
    scheduler: Any | None = None,
) -> dict[str, Any]:
    """Deploy a generated skill into the running system with rollback on failure.

    If load_skill or cron registration fails, the skill directory is removed
    so the system is left in a clean state.

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
        logger.exception("Failed to load skill '%s' — rolling back", name)
        _cleanup_dir(skill_dir)
        return {"status": "error", "message": f"load failed: {e}"}

    # Register cron — if this fails, unload skill + remove dir
    if scheduler:
        try:
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
                    scheduler.register_cron(name, cron, topic=f"skill.{name}.trigger")
        except ValueError as e:
            logger.warning("Invalid cron for skill '%s': %s — skill deployed without schedule", name, e)
            # Not fatal: skill still works on-demand
        except Exception as e:
            logger.exception("Cron registration failed for '%s' — rolling back", name)
            try:
                if hasattr(skill_executor, "unload_skill"):
                    skill_executor.unload_skill(name)
            except Exception:
                pass
            _cleanup_dir(skill_dir)
            return {"status": "error", "message": f"schedule failed: {e}"}

    logger.info("Deployed skill: %s", name)
    return {"status": "deployed", "name": name}


async def deploy_agent(
    agent_dir: Path,
    plugin_registry: Any,
    agent_runtime: Any,
) -> dict[str, Any]:
    """Deploy a generated agent with rollback and health check.

    Steps:
    1. Discover manifest in registry
    2. Load agent via runtime
    3. Health check — if fails, unload + remove dir
    4. Any exception → remove dir

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
            _cleanup_dir(agent_dir)
            return {"status": "error", "message": f"Manifest not found for '{name}'"}

        await agent_runtime.load_agent(name)

        # Health check — if agent crashes immediately, roll back
        try:
            status = await agent_runtime.get_status(name)
            if status.get("status") not in ("running", "healthy", "ok"):
                logger.warning("Agent '%s' health check failed: %s — rolling back", name, status)
                try:
                    await agent_runtime.unload_agent(name)
                except Exception:
                    pass
                _cleanup_dir(agent_dir)
                return {"status": "error", "message": f"health check failed: {status}"}
        except Exception:
            # get_status might not exist for all protocols — non-fatal
            pass

    except Exception as e:
        logger.exception("Failed to deploy agent '%s' — rolling back", name)
        try:
            await agent_runtime.unload_agent(name)
        except Exception:
            pass
        _cleanup_dir(agent_dir)
        return {"status": "error", "message": str(e)}

    logger.info("Deployed agent: %s", name)
    return {"status": "deployed", "name": name}
