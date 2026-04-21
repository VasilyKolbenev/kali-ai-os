"""Agent Skills spec frontmatter validation.

Implements the validation rules from https://agentskills.io/specification:

Required fields:
- name: 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing/consecutive hyphens
- description: 1-1024 chars, non-empty

Optional fields:
- license: str (name or file reference)
- compatibility: str, max 500 chars
- metadata: dict[str, str]
- allowed-tools: str (space-separated tool names)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Strict per-spec validation
_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$|^[a-z0-9]$")
_NAME_MAX_LEN = 64
_DESCRIPTION_MAX_LEN = 1024
_COMPATIBILITY_MAX_LEN = 500


class ValidationError(ValueError):
    """Raised when a skill's frontmatter violates the Agent Skills spec."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"[{field}] {message}")


@dataclass
class ValidationResult:
    """Outcome of frontmatter validation."""

    valid: bool
    errors: list[str]
    warnings: list[str]


def _validate_name(name: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(name, str):
        errors.append(f"name must be a string, got {type(name).__name__}")
        return errors
    if not name:
        errors.append("name is required and must not be empty")
        return errors
    if len(name) > _NAME_MAX_LEN:
        errors.append(f"name exceeds {_NAME_MAX_LEN} characters ({len(name)})")
    if name.startswith("-"):
        errors.append("name must not start with a hyphen")
    if name.endswith("-"):
        errors.append("name must not end with a hyphen")
    if "--" in name:
        errors.append("name must not contain consecutive hyphens")
    if not _NAME_PATTERN.fullmatch(name):
        errors.append(
            "name must contain only lowercase letters, digits, and hyphens"
        )
    return errors


def _validate_description(description: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(description, str):
        errors.append(f"description must be a string, got {type(description).__name__}")
        return errors
    stripped = description.strip()
    if not stripped:
        errors.append("description is required and must not be empty")
        return errors
    if len(description) > _DESCRIPTION_MAX_LEN:
        errors.append(
            f"description exceeds {_DESCRIPTION_MAX_LEN} characters ({len(description)})"
        )
    return errors


def _validate_license(value: Any) -> list[str]:
    if not isinstance(value, str):
        return [f"license must be a string, got {type(value).__name__}"]
    return []


def _validate_compatibility(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, str):
        errors.append(f"compatibility must be a string, got {type(value).__name__}")
        return errors
    if len(value) > _COMPATIBILITY_MAX_LEN:
        errors.append(
            f"compatibility exceeds {_COMPATIBILITY_MAX_LEN} characters ({len(value)})"
        )
    return errors


def _validate_metadata(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        errors.append(f"metadata must be a mapping, got {type(value).__name__}")
        return errors
    for k, v in value.items():
        if not isinstance(k, str):
            errors.append(f"metadata keys must be strings (got {type(k).__name__})")
        if not isinstance(v, (str, int, float, bool)):
            errors.append(
                f"metadata['{k}'] must be a scalar value, got {type(v).__name__}"
            )
    return errors


def _validate_allowed_tools(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, str):
        errors.append(f"allowed-tools must be a string, got {type(value).__name__}")
    return errors


def validate_frontmatter(
    frontmatter: dict[str, Any],
    *,
    expected_name: str | None = None,
) -> ValidationResult:
    """Validate SKILL.md frontmatter against Agent Skills spec.

    Args:
        frontmatter: Parsed YAML frontmatter dict.
        expected_name: If provided, ensures `name` matches the parent directory.

    Returns:
        ValidationResult with errors + warnings lists.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Required fields
    errors.extend(_validate_name(frontmatter.get("name")))
    errors.extend(_validate_description(frontmatter.get("description")))

    # Optional fields — only validate if present
    if "license" in frontmatter:
        errors.extend(_validate_license(frontmatter["license"]))
    if "compatibility" in frontmatter:
        errors.extend(_validate_compatibility(frontmatter["compatibility"]))
    if "metadata" in frontmatter:
        errors.extend(_validate_metadata(frontmatter["metadata"]))
    if "allowed-tools" in frontmatter:
        errors.extend(_validate_allowed_tools(frontmatter["allowed-tools"]))

    # Cross-field: name must match directory
    if expected_name is not None:
        name = frontmatter.get("name")
        if isinstance(name, str) and name != expected_name:
            errors.append(
                f"name '{name}' does not match parent directory '{expected_name}'"
            )

    # Warnings (non-fatal)
    desc = frontmatter.get("description", "")
    if isinstance(desc, str) and len(desc) < 40:
        warnings.append(
            "description is very short — add keywords describing when to use the skill "
            "for better LLM discovery"
        )

    # Unknown top-level keys
    _known_keys = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    unknown = set(frontmatter.keys()) - _known_keys
    if unknown:
        warnings.append(
            f"unknown frontmatter keys (may be ignored by other agents): {sorted(unknown)}"
        )

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
