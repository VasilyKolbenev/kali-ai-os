"""Legacy manifest.yaml → SKILL.md converter.

During migration (Phase 6 of roadmap), existing agents with manifest.yaml are
converted to the Agent Skills spec format. This preserves the original folder
structure but adds SKILL.md alongside (or replaces) manifest.yaml.

Usage:
    from kernel.skills.converter import convert_agent_to_skill
    skill_path = convert_agent_to_skill(Path("agents/weather"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from kernel.skills.loader import SkillManifest, save_skill

logger = logging.getLogger(__name__)


class ConversionError(RuntimeError):
    """Raised when legacy agent cannot be converted."""


def _derive_description(manifest: dict[str, Any]) -> str:
    """Build a spec-compliant description from legacy fields.

    Legacy `description` is often one sentence; spec prefers "what + when to use"
    format. We pad with tool hints when we can.
    """
    base = str(manifest.get("description", "")).strip()
    tools = manifest.get("tools") or []
    capabilities = manifest.get("capabilities") or []

    if not base and capabilities:
        base = f"Provides {', '.join(capabilities[:3])}."
    if not base:
        base = f"Legacy agent '{manifest.get('name', 'unknown')}'."

    # Append when-to-use hint if description doesn't have one
    lower = base.lower()
    if not any(k in lower for k in ("use when", "when user", "use for", "для ")):
        tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
        if tool_names:
            base += f" Use when user mentions {', '.join(tool_names[:3])}."

    return base[:1024]


def _build_body(manifest: dict[str, Any], legacy_dir: Path) -> str:
    """Compose the SKILL.md Markdown body from legacy manifest hints."""
    name = manifest.get("name", legacy_dir.name)
    capabilities = manifest.get("capabilities") or []
    tools = manifest.get("tools") or []

    lines: list[str] = [f"# {name}", ""]

    if capabilities:
        lines.append("## Capabilities")
        for cap in capabilities:
            lines.append(f"- {cap}")
        lines.append("")

    if tools:
        lines.append("## Actions")
        for tool in tools:
            if isinstance(tool, dict):
                tname = tool.get("name", "?")
                tdesc = tool.get("description", "").strip()
                lines.append(f"- **{tname}** — {tdesc}" if tdesc else f"- **{tname}**")
            else:
                lines.append(f"- {tool}")
        lines.append("")

    # Point to legacy agent.py if present
    if (legacy_dir / "agent.py").is_file():
        lines.extend([
            "## Implementation",
            "",
            "This skill wraps a legacy `agent.py` script. The runtime calls ",
            "`CustomAgent.handle_action(action, args)` in-process.",
            "",
            "See `scripts/agent.py` for the implementation.",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def convert_agent_to_skill(
    legacy_dir: Path | str,
    *,
    target_dir: Path | str | None = None,
    move_scripts: bool = True,
    dry_run: bool = False,
) -> Path:
    """Convert a legacy agent directory to the SKILL.md format.

    Args:
        legacy_dir: Agent dir containing manifest.yaml (+ agent.py typically).
        target_dir: Where to write the SKILL.md skill (defaults to legacy_dir).
        move_scripts: If True, copy agent.py into scripts/agent.py.
        dry_run: If True, compute result but do not write files.

    Returns:
        Path to the created skill directory.

    Raises:
        ConversionError: If manifest.yaml is missing or malformed.
    """
    import shutil

    legacy_dir = Path(legacy_dir).resolve()
    manifest_path = legacy_dir / "manifest.yaml"

    if not manifest_path.is_file():
        raise ConversionError(f"No manifest.yaml in {legacy_dir}")

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConversionError(f"Malformed manifest.yaml: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConversionError(f"manifest.yaml must be a mapping, got {type(raw).__name__}")

    name = str(raw.get("name", legacy_dir.name))
    description = _derive_description(raw)
    body = _build_body(raw, legacy_dir)

    # Preserve provenance in metadata
    metadata: dict[str, str] = {
        "migrated_from": "legacy_manifest_v1",
        "original_version": str(raw.get("version", "1.0.0")),
    }
    if "author" in raw:
        metadata["author"] = str(raw["author"])

    # Legacy permissions → compatibility hint
    compat_parts: list[str] = []
    perms = raw.get("permissions") or []
    if isinstance(perms, list):
        net_perms = [p for p in perms if "network" in str(p)]
        if net_perms:
            compat_parts.append("requires network access")
    if "protocol" in raw and raw["protocol"] != "native":
        compat_parts.append(f"protocol={raw['protocol']}")
    compatibility = "; ".join(compat_parts) or None

    # allowed-tools from legacy tools list
    tool_names = [
        str(t.get("name")) for t in (raw.get("tools") or [])
        if isinstance(t, dict) and t.get("name")
    ]
    allowed_tools = " ".join(tool_names) if tool_names else None

    dest = Path(target_dir).resolve() if target_dir else legacy_dir

    manifest_obj = SkillManifest(
        name=name,
        description=description,
        body=body,
        license=str(raw.get("license", "")) or None,
        compatibility=compatibility,
        metadata=metadata,
        allowed_tools=allowed_tools,
        skill_dir=dest,
        source="migrated",
    )

    if dry_run:
        logger.info("[dry-run] would create SKILL.md at %s", dest / "SKILL.md")
        return dest

    dest.mkdir(parents=True, exist_ok=True)
    skill_md = save_skill(manifest_obj, skill_dir=dest)
    logger.info("Converted %s → %s", manifest_path, skill_md)

    # Move agent.py into scripts/ if requested and scripts/ doesn't already exist
    if move_scripts:
        legacy_script = legacy_dir / "agent.py"
        if legacy_script.is_file():
            scripts_dir = dest / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            target_script = scripts_dir / "agent.py"
            if not target_script.exists():
                if dest == legacy_dir:
                    # Same dir: copy (don't delete original to avoid breaking old runtime)
                    shutil.copy2(legacy_script, target_script)
                else:
                    shutil.copy2(legacy_script, target_script)
                logger.info("Copied %s → %s", legacy_script, target_script)

    return dest


def convert_all_legacy_agents(
    agents_root: Path | str,
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Convert every legacy agent under ``agents_root`` to SKILL.md format.

    Args:
        agents_root: Parent dir containing multiple agent folders.
        dry_run: If True, report planned conversions without writing.

    Returns:
        List of successfully converted skill directories.
    """
    root = Path(agents_root).resolve()
    if not root.is_dir():
        logger.warning("agents_root does not exist: %s", root)
        return []

    converted: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):  # skip _base, __pycache__
            continue
        if not (entry / "manifest.yaml").is_file():
            continue
        # Skip if already converted
        if (entry / "SKILL.md").is_file():
            logger.debug("Skipping %s — SKILL.md already exists", entry.name)
            continue
        try:
            result = convert_agent_to_skill(entry, dry_run=dry_run)
            converted.append(result)
        except ConversionError as exc:
            logger.warning("Failed to convert %s: %s", entry.name, exc)
        except Exception:
            logger.exception("Unexpected error converting %s", entry.name)

    logger.info("Converted %d/%d legacy agents", len(converted), sum(1 for _ in root.iterdir() if _.is_dir()))
    return converted
