"""Tests for SKILL.md loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.skills.loader import (
    SkillParseError,
    _split_frontmatter,
    load_skill,
    save_skill,
    SkillManifest,
)
from kernel.skills.validator import ValidationError


class TestSplitFrontmatter:
    def test_basic_parse(self):
        content = "---\nname: x\ndescription: y\n---\n\nBody\n"
        fm, body = _split_frontmatter(content)
        assert fm == {"name": "x", "description": "y"}
        assert body.strip() == "Body"

    def test_empty_body_allowed(self):
        content = "---\nname: x\ndescription: y\n---\n"
        fm, body = _split_frontmatter(content)
        assert fm == {"name": "x", "description": "y"}
        assert body == ""

    def test_leading_blank_lines(self):
        content = "\n\n---\nname: x\ndescription: y\n---\n\nBody\n"
        fm, body = _split_frontmatter(content)
        assert fm["name"] == "x"

    def test_missing_opening_delim(self):
        with pytest.raises(SkillParseError, match="begin with"):
            _split_frontmatter("name: x\n---\nBody")

    def test_missing_closing_delim(self):
        with pytest.raises(SkillParseError, match="Unterminated"):
            _split_frontmatter("---\nname: x\ndescription: y\n\nBody with no close")

    def test_invalid_yaml(self):
        with pytest.raises(SkillParseError, match="Invalid YAML"):
            _split_frontmatter("---\nname: [unclosed\n---\n")

    def test_non_mapping_frontmatter(self):
        with pytest.raises(SkillParseError, match="mapping"):
            _split_frontmatter("---\n- item1\n- item2\n---\n")

    def test_empty_file(self):
        with pytest.raises(SkillParseError):
            _split_frontmatter("")


class TestLoadSkill:
    def _make_skill(self, tmp_path: Path, name: str, body: str = "Body") -> Path:
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test skill with enough description text to pass.\n---\n\n{body}\n",
            encoding="utf-8",
        )
        return d

    def test_load_basic(self, tmp_path):
        d = self._make_skill(tmp_path, "test-skill")
        m = load_skill(d)
        assert m.name == "test-skill"
        assert "enough description" in m.description
        assert m.body.strip() == "Body"
        assert m.source == "unknown"

    def test_load_with_source_tag(self, tmp_path):
        d = self._make_skill(tmp_path, "tagged")
        m = load_skill(d, source="builtin")
        assert m.source == "builtin"

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_skill(tmp_path / "nonexistent")

    def test_load_detects_scripts_dir(self, tmp_path):
        d = self._make_skill(tmp_path, "scripted")
        (d / "scripts").mkdir()
        (d / "scripts" / "main.py").write_text("print('hi')")
        m = load_skill(d)
        assert m.has_scripts

    def test_load_detects_references_dir(self, tmp_path):
        d = self._make_skill(tmp_path, "ref-skill")
        (d / "references").mkdir()
        (d / "references" / "REFERENCE.md").write_text("# ref")
        m = load_skill(d)
        assert m.has_references

    def test_load_detects_assets_dir(self, tmp_path):
        d = self._make_skill(tmp_path, "asset-skill")
        (d / "assets").mkdir()
        m = load_skill(d)
        assert m.has_assets

    def test_load_strict_raises_on_invalid(self, tmp_path):
        d = tmp_path / "BadName"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: BadName\ndescription: Test.\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            load_skill(d, strict=True)

    def test_load_non_strict_returns_manifest(self, tmp_path):
        d = tmp_path / "BadName"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: BadName\ndescription: Test.\n---\n",
            encoding="utf-8",
        )
        # Returns best-effort manifest; no raise
        m = load_skill(d, strict=False)
        assert m.name == "BadName"


class TestAllowedTools:
    def test_empty_tool_list(self):
        m = SkillManifest(name="x", description="y", body="")
        assert m.tool_list == []

    def test_parse_multiple_tools(self):
        m = SkillManifest(
            name="x", description="y", body="",
            allowed_tools="Read Write Bash(git:*)",
        )
        assert m.tool_list == ["Read", "Write", "Bash(git:*)"]


class TestSaveSkill:
    def test_roundtrip(self, tmp_path):
        original = SkillManifest(
            name="round-trip",
            description="Tests that save/load is lossless for all fields.",
            body="# Hello\n\nBody text.\n",
            license="MIT",
            metadata={"author": "kali", "version": "1.0"},
            allowed_tools="Read Write",
            skill_dir=tmp_path / "round-trip",
        )
        skill_md = save_skill(original)
        assert skill_md.is_file()

        loaded = load_skill(tmp_path / "round-trip")
        assert loaded.name == "round-trip"
        assert loaded.license == "MIT"
        assert loaded.metadata == {"author": "kali", "version": "1.0"}
        assert loaded.allowed_tools == "Read Write"
        assert "Hello" in loaded.body

    def test_save_unicode(self, tmp_path):
        m = SkillManifest(
            name="cyrillic",
            description="Описание с русскими буквами и символами. Use for RU text.",
            body="# Заголовок\n\nТекст на русском.\n",
            skill_dir=tmp_path / "cyrillic",
        )
        save_skill(m)
        loaded = load_skill(tmp_path / "cyrillic")
        assert "русскими" in loaded.description
        assert "русском" in loaded.body
