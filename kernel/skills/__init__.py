"""KALI Skills — native Agent Skills spec support.

Implements the open Agent Skills specification (https://agentskills.io):
- SKILL.md as the canonical skill format (YAML frontmatter + Markdown body)
- Hybrid discovery: bundled built-ins + user-installed in AppData
- Backward compatibility with legacy manifest.yaml format during migration

Module layout:
- loader.py — SKILL.md parser (frontmatter + body)
- validator.py — spec-compliant validation
- registry.py — hybrid discovery from multiple sources
- converter.py — legacy manifest.yaml → SKILL.md migration
- runtime.py — skill execution (LLM instructions + scripts)
"""

from kernel.skills.loader import SkillManifest, load_skill
from kernel.skills.validator import ValidationError, validate_frontmatter

__all__ = [
    "SkillManifest",
    "load_skill",
    "ValidationError",
    "validate_frontmatter",
]
