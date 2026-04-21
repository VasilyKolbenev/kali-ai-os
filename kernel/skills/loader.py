"""SKILL.md parser — loads Agent Skills spec files into structured manifests.

Format (per https://agentskills.io/specification):

    ---
    name: skill-name
    description: What it does and when to use it.
    license: MIT
    compatibility: Requires Python 3.12+
    metadata:
      author: someone
      version: "1.0"
    allowed-tools: Read Write Bash(git:*)
    ---

    # Skill body (Markdown)

    Instructions for the agent to follow when this skill is active.

Directory structure:

    skill-name/
    ├── SKILL.md          # Required
    ├── scripts/          # Optional: executable code
    ├── references/       # Optional: detailed docs
    └── assets/           # Optional: static resources
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kernel.skills.validator import ValidationResult, validate_frontmatter

logger = logging.getLogger(__name__)

_FRONTMATTER_DELIM = "---"


@dataclass
class SkillManifest:
    """A parsed SKILL.md file.

    Attributes:
        name: Unique skill identifier (matches directory name).
        description: What the skill does and when to use it.
        body: Markdown instructions for the agent.
        license: Optional license name or reference.
        compatibility: Optional environment requirements.
        metadata: Optional arbitrary key-value pairs.
        allowed_tools: Optional space-separated tool allowlist.
        skill_dir: Absolute path to the skill directory.
        scripts_dir: Path to scripts/ if exists.
        references_dir: Path to references/ if exists.
        assets_dir: Path to assets/ if exists.
        source: Origin identifier — "builtin", "user", "catalog:anthropic", etc.
    """

    name: str
    description: str
    body: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_tools: str | None = None
    skill_dir: Path = field(default_factory=lambda: Path("."))
    scripts_dir: Path | None = None
    references_dir: Path | None = None
    assets_dir: Path | None = None
    source: str = "unknown"

    @property
    def has_scripts(self) -> bool:
        return self.scripts_dir is not None and self.scripts_dir.exists()

    @property
    def has_references(self) -> bool:
        return self.references_dir is not None and self.references_dir.exists()

    @property
    def has_assets(self) -> bool:
        return self.assets_dir is not None and self.assets_dir.exists()

    @property
    def tool_list(self) -> list[str]:
        """Parse allowed-tools into a list. Empty if None."""
        if not self.allowed_tools:
            return []
        return self.allowed_tools.split()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict (for API responses)."""
        return {
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": dict(self.metadata),
            "allowed_tools": self.allowed_tools,
            "allowed_tools_list": self.tool_list,
            "skill_dir": str(self.skill_dir),
            "has_scripts": self.has_scripts,
            "has_references": self.has_references,
            "has_assets": self.has_assets,
            "source": self.source,
        }


class SkillParseError(ValueError):
    """Raised when SKILL.md cannot be parsed."""


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and Markdown body from raw file content.

    Returns:
        Tuple of (frontmatter_dict, body_markdown).

    Raises:
        SkillParseError: If frontmatter delimiters are missing or YAML is invalid.
    """
    lines = content.splitlines(keepends=True)
    if not lines:
        raise SkillParseError("SKILL.md is empty")

    # First non-empty line must be the opening delimiter
    first_idx = 0
    while first_idx < len(lines) and not lines[first_idx].strip():
        first_idx += 1

    if first_idx >= len(lines) or lines[first_idx].strip() != _FRONTMATTER_DELIM:
        raise SkillParseError(
            "SKILL.md must begin with YAML frontmatter delimited by '---'"
        )

    # Find closing delimiter
    end_idx = None
    for i in range(first_idx + 1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIM:
            end_idx = i
            break

    if end_idx is None:
        raise SkillParseError(
            "Unterminated frontmatter: missing closing '---'"
        )

    frontmatter_text = "".join(lines[first_idx + 1 : end_idx])
    body = "".join(lines[end_idx + 1 :]).lstrip("\n")

    try:
        data = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise SkillParseError(
            f"Frontmatter must be a mapping, got {type(data).__name__}"
        )

    return data, body


def load_skill(
    skill_dir: Path | str,
    *,
    source: str = "unknown",
    strict: bool = True,
) -> SkillManifest:
    """Load a SKILL.md file from a skill directory.

    Args:
        skill_dir: Path to skill directory (must contain SKILL.md).
        source: Origin tag (e.g. "builtin", "user", "catalog:anthropic").
        strict: If True, raise ValidationError on spec violations.
                If False, log warnings but return best-effort manifest.

    Returns:
        Parsed SkillManifest.

    Raises:
        FileNotFoundError: If SKILL.md is missing.
        SkillParseError: If file is malformed.
        ValidationError: If strict=True and validation fails.
    """
    skill_dir = Path(skill_dir).resolve()
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    content = skill_md.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(content)

    # Validate against spec
    result: ValidationResult = validate_frontmatter(
        frontmatter, expected_name=skill_dir.name
    )

    if result.warnings:
        for w in result.warnings:
            logger.warning("Skill '%s': %s", skill_dir.name, w)

    if not result.valid:
        msg = f"Invalid SKILL.md in {skill_dir}: {'; '.join(result.errors)}"
        if strict:
            from kernel.skills.validator import ValidationError
            raise ValidationError("frontmatter", msg)
        logger.warning(msg)

    # Resolve optional subdirectories
    scripts_dir = skill_dir / "scripts"
    refs_dir = skill_dir / "references"
    assets_dir = skill_dir / "assets"

    manifest = SkillManifest(
        name=str(frontmatter.get("name", skill_dir.name)),
        description=str(frontmatter.get("description", "")),
        body=body,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        metadata=dict(frontmatter.get("metadata") or {}),
        allowed_tools=frontmatter.get("allowed-tools"),
        skill_dir=skill_dir,
        scripts_dir=scripts_dir if scripts_dir.is_dir() else None,
        references_dir=refs_dir if refs_dir.is_dir() else None,
        assets_dir=assets_dir if assets_dir.is_dir() else None,
        source=source,
    )

    return manifest


def save_skill(manifest: SkillManifest, skill_dir: Path | str | None = None) -> Path:
    """Write a SkillManifest back to SKILL.md format.

    Used by the converter and publishing flow.

    Args:
        manifest: The manifest to serialize.
        skill_dir: Override target directory (defaults to manifest.skill_dir).

    Returns:
        Path to the written SKILL.md file.
    """
    target_dir = Path(skill_dir) if skill_dir else manifest.skill_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    frontmatter: dict[str, Any] = {
        "name": manifest.name,
        "description": manifest.description,
    }
    if manifest.license:
        frontmatter["license"] = manifest.license
    if manifest.compatibility:
        frontmatter["compatibility"] = manifest.compatibility
    if manifest.metadata:
        frontmatter["metadata"] = dict(manifest.metadata)
    if manifest.allowed_tools:
        frontmatter["allowed-tools"] = manifest.allowed_tools

    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()

    content = f"---\n{yaml_text}\n---\n\n{manifest.body.lstrip()}"
    skill_md = target_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return skill_md
