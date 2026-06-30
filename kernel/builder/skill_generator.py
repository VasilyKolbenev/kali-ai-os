"""Skill generator — creates manifest.yaml + skill.yaml from a structured spec."""

from __future__ import annotations

import logging
import re
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

# Russian number words for spelled-out intervals ("каждые два часа") — voice STT
# often transcribes small numbers as words rather than digits.
_RU_NUM: dict[str, int] = {
    "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "двенадцать": 12,
}


def _parse_interval_hours(text: str) -> int | None:
    """Parse 'каждые 2 часа' / 'каждый час' / 'раз в час' / 'ежечасно' → hours."""
    t = text.lower()
    m = re.search(r"(\d+)\s*час", t)
    if m:
        return max(1, int(m.group(1)))
    for word, n in _RU_NUM.items():
        if re.search(rf"\b{word}\w*\s+час", t):
            return n
    if "час" in t or "ежечас" in t:
        return 1
    return None


def _parse_interval_minutes(text: str) -> int | None:
    """Parse 'каждые 30 минут' / 'полчаса' → minutes."""
    t = text.lower()
    m = re.search(r"(\d+)\s*мин", t)
    if m:
        return max(1, int(m.group(1)))
    if "пол" in t and "час" in t:
        return 30
    return None


def _with_schedule(config: dict[str, Any]) -> dict[str, Any]:
    """Derive the deployer's schedule keys from the wizard's free-text answer.

    The wizard records "Как часто…?" as a flat ``interval`` string (e.g.
    "каждые 2 часа"), but the deployer only registers a cron when it finds
    ``reminders.interval_hours`` or ``schedule.cron`` — so a time-based skill
    previously never got scheduled. Returns a new config with those keys filled
    in; leaves an already-structured schedule untouched.
    """
    reminders = config.get("reminders")
    schedule = config.get("schedule")
    if (isinstance(reminders, dict) and reminders.get("interval_hours")) or (
        isinstance(schedule, dict) and schedule.get("cron")
    ):
        return config

    raw = config.get("interval") or config.get("time_window") or ""
    if not isinstance(raw, str) or not raw.strip():
        return config

    new = dict(config)
    minutes = _parse_interval_minutes(raw)
    if minutes:
        new["schedule"] = {"cron": f"*/{minutes} * * * *"}
        return new
    hours = _parse_interval_hours(raw)
    if hours:
        new["reminders"] = {"enabled": True, "interval_hours": hours}
    return new


def _dedup_name(agents_dir: Path, name: str) -> str:
    """Return a directory name under ``agents_dir`` that does not yet exist.

    If ``name`` is free it is returned unchanged; otherwise a numeric suffix
    (``-2``, ``-3``, …) is appended until a free name is found. This prevents a
    colliding slug from silently overwriting a pre-existing agent.

    Args:
        agents_dir: Base directory the skill directory will be created under.
        name: Desired (already-validated) kebab-case skill name.

    Returns:
        A name guaranteed not to collide with an existing directory.
    """
    if not (agents_dir / name).exists():
        return name
    suffix = 2
    while (agents_dir / f"{name}-{suffix}").exists():
        suffix += 1
    return f"{name}-{suffix}"


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
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid agent name: {name}")

    # Translate the wizard's free-text interval into the schedule keys the
    # deployer reads, so a time-based skill actually gets a cron registered.
    config = _with_schedule(config)

    # De-dup a colliding slug so a voice-built skill never silently overwrites
    # a pre-existing agent (data loss). The first 'foo' keeps its dir; the next
    # becomes 'foo-2', etc.
    agents_dir.mkdir(parents=True, exist_ok=True)
    name = _dedup_name(agents_dir, name)

    skill_dir = agents_dir / name
    skill_dir.mkdir(parents=True, exist_ok=False)

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
