"""Skill generator — creates manifest.yaml + skill.yaml from a structured spec."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Standard tools bundled with each template type
_TEMPLATE_TOOLS: dict[str, list[dict[str, Any]]] = {
    "tracker": [
        {"name": "log", "description": "Log a new data point", "parameters": {}},
        {"name": "summary", "description": "Summarise tracked data", "parameters": {}},
        {"name": "trend", "description": "Show trend over time", "parameters": {}},
    ],
    "reminder": [
        {"name": "check", "description": "Check pending reminders", "parameters": {}},
        {"name": "snooze", "description": "Snooze a reminder", "parameters": {}},
    ],
    "monitor": [
        {"name": "check", "description": "Run a monitoring check", "parameters": {}},
        {"name": "history", "description": "Show check history", "parameters": {}},
        {"name": "alert", "description": "Trigger an alert", "parameters": {}},
    ],
    "notifier": [
        {"name": "notify", "description": "Send a notification", "parameters": {}},
        {"name": "log", "description": "View notification log", "parameters": {}},
    ],
    "logger": [
        {"name": "add_entry", "description": "Add a new log entry", "parameters": {}},
        {"name": "list_entries", "description": "List recent entries", "parameters": {}},
        {"name": "search", "description": "Search log entries", "parameters": {}},
    ],
}

# Fallback tools for unknown template types
_DEFAULT_TOOLS: list[dict[str, Any]] = [
    {"name": "run", "description": "Execute the skill", "parameters": {}},
    {"name": "status", "description": "Report skill status", "parameters": {}},
]


def generate_skill(
    name: str,
    template: str,
    description: str,
    config: dict[str, Any],
    agents_dir: Path,
) -> Path:
    """Generate a YAML-based skill in agents/{name}/.

    Creates two files:
    - ``manifest.yaml`` — agent identity, capabilities, and tools.
    - ``skill.yaml``   — skill-specific configuration and template metadata.

    Args:
        name: Kebab-case identifier for the skill (e.g. "water-tracker").
        template: Template type key (e.g. "tracker", "reminder").
        description: Human-readable description of what the skill does.
        config: Arbitrary configuration dict embedded in skill.yaml.
        agents_dir: Base directory under which ``{name}/`` will be created.

    Returns:
        Path to the newly created skill directory.

    Raises:
        OSError: If the directory cannot be created or files cannot be written.
    """
    skill_dir = agents_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    tools = _TEMPLATE_TOOLS.get(template, _DEFAULT_TOOLS)
    capabilities = [f"{name}.{tool['name']}" for tool in tools]

    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "template": template,
        "capabilities": capabilities,
        "tools": tools,
        "protocol": "skill",
        "permissions": [],
    }

    skill_config: dict[str, Any] = {
        "template": template,
        "description": description,
        "config": config,
        "schedule": config.get("schedule", None),
    }

    manifest_path = skill_dir / "manifest.yaml"
    skill_path = skill_dir / "skill.yaml"

    manifest_path.write_text(
        yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    skill_path.write_text(
        yaml.dump(skill_config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    logger.info("Skill '%s' (template=%s) created at %s", name, template, skill_dir)
    return skill_dir
