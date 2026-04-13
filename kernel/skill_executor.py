"""Skill executor — runs skill templates in-process from YAML config."""

import logging
from pathlib import Path
from typing import Any

import yaml

from kernel.skill_templates.base import SkillTemplate
from kernel.skill_templates.logger import LoggerTemplate
from kernel.skill_templates.monitor import MonitorTemplate
from kernel.skill_templates.notifier import NotifierTemplate
from kernel.skill_templates.reminder import ReminderTemplate
from kernel.skill_templates.tracker import TrackerTemplate

logger = logging.getLogger(__name__)

TEMPLATE_REGISTRY: dict[str, type[SkillTemplate]] = {
    "tracker": TrackerTemplate,
    "reminder": ReminderTemplate,
    "monitor": MonitorTemplate,
    "notifier": NotifierTemplate,
    "logger": LoggerTemplate,
}


class SkillExecutor:
    """Loads and executes skills in-process using template classes."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._skills: dict[str, dict[str, Any]] = {}

    def load_skill(self, skill_dir: Path) -> None:
        """Load skill from directory containing skill.yaml.

        Args:
            skill_dir: Path to directory with skill.yaml file.

        Raises:
            FileNotFoundError: If skill.yaml is missing.
            ValueError: If template name is unknown.
        """
        skill_yaml_path = skill_dir / "skill.yaml"
        if not skill_yaml_path.exists():
            raise FileNotFoundError(f"No skill.yaml in {skill_dir}")
        with open(skill_yaml_path) as f:
            skill_yaml = yaml.safe_load(f)
        template_name = skill_yaml.get("template")
        if template_name not in TEMPLATE_REGISTRY:
            raise ValueError(f"Unknown template '{template_name}'")
        name = skill_dir.name
        template_cls = TEMPLATE_REGISTRY[template_name]
        template = template_cls(skill_name=name, data_dir=self._data_dir)
        self._skills[name] = {
            "template": template,
            "config": skill_yaml.get("config", {}),
            "skill_yaml": skill_yaml,
        }
        logger.info("Loaded skill '%s' (template: %s)", name, template_name)

    async def execute(
        self,
        skill_name: str,
        action: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a skill action.

        Args:
            skill_name: Name of the loaded skill.
            action: Action to perform (template-specific).
            args: Optional action arguments.

        Returns:
            Result dict from the template.

        Raises:
            ValueError: If skill is not loaded.
        """
        if skill_name not in self._skills:
            raise ValueError(f"Skill '{skill_name}' not found")
        skill = self._skills[skill_name]
        return await skill["template"].execute(action, args or {}, skill["config"])

    def list_skills(self) -> list[str]:
        """Return names of all loaded skills."""
        return list(self._skills.keys())

    def get_skill_info(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a loaded skill, or None if not found.

        Args:
            name: Skill name to look up.

        Returns:
            Dict with name, template, config, display_name; or None.
        """
        skill = self._skills.get(name)
        if not skill:
            return None
        return {
            "name": name,
            "template": skill["template"].template_name,
            "config": skill["config"],
            "display_name": skill["skill_yaml"].get("display_name", name),
        }

    def unload_skill(self, name: str) -> bool:
        """Remove a skill from the executor.

        Args:
            name: Skill name to unload.

        Returns:
            True if skill was found and removed, False otherwise.
        """
        return self._skills.pop(name, None) is not None
