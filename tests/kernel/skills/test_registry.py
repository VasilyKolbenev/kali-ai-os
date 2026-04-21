"""Tests for SkillsRegistry hybrid discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.skills.registry import SkillSource, SkillsRegistry


def _create_skill(root: Path, name: str, description: str = "A test skill.") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description} Use when testing.\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return d


class TestDiscovery:
    def test_empty_sources(self, tmp_path):
        sources = [SkillSource(name="empty", path=tmp_path, read_only=True)]
        reg = SkillsRegistry(sources=sources)
        reg.discover()
        assert reg.list_all() == []

    def test_discover_single_source(self, tmp_path):
        _create_skill(tmp_path, "skill-a")
        _create_skill(tmp_path, "skill-b")

        reg = SkillsRegistry(
            sources=[SkillSource(name="test", path=tmp_path, read_only=True)]
        )
        reg.discover()

        names = [s.name for s in reg.list_all()]
        assert names == ["skill-a", "skill-b"]

    def test_ignores_non_skill_directories(self, tmp_path):
        _create_skill(tmp_path, "real-skill")
        (tmp_path / "_base").mkdir()  # should be ignored (no SKILL.md)
        (tmp_path / "regular-folder").mkdir()

        reg = SkillsRegistry(
            sources=[SkillSource(name="test", path=tmp_path, read_only=True)]
        )
        reg.discover()
        assert len(reg.list_all()) == 1
        assert reg.list_all()[0].name == "real-skill"

    def test_ignores_files_at_root(self, tmp_path):
        (tmp_path / "random.txt").write_text("ignore me")
        _create_skill(tmp_path, "good")

        reg = SkillsRegistry(
            sources=[SkillSource(name="test", path=tmp_path, read_only=True)]
        )
        reg.discover()
        assert len(reg.list_all()) == 1


class TestOverridePrecedence:
    def test_user_overrides_builtin(self, tmp_path):
        builtin_dir = tmp_path / "builtin"
        user_dir = tmp_path / "user"
        builtin_dir.mkdir()
        user_dir.mkdir()

        _create_skill(builtin_dir, "shared-name", description="Built-in version.")
        _create_skill(user_dir, "shared-name", description="User override version.")

        # user source FIRST in list → should win collisions
        sources = [
            SkillSource(name="user", path=user_dir, read_only=False),
            SkillSource(name="builtin", path=builtin_dir, read_only=True),
        ]
        reg = SkillsRegistry(sources=sources)
        reg.discover()

        skill = reg.get("shared-name")
        assert skill is not None
        assert skill.source == "user"
        assert "User override" in skill.description

    def test_unique_skills_from_both_sources(self, tmp_path):
        builtin_dir = tmp_path / "builtin"
        user_dir = tmp_path / "user"
        builtin_dir.mkdir()
        user_dir.mkdir()

        _create_skill(builtin_dir, "from-builtin")
        _create_skill(user_dir, "from-user")

        reg = SkillsRegistry(sources=[
            SkillSource(name="user", path=user_dir, read_only=False),
            SkillSource(name="builtin", path=builtin_dir, read_only=True),
        ])
        reg.discover()

        assert len(reg.list_all()) == 2
        assert reg.get("from-builtin").source == "builtin"
        assert reg.get("from-user").source == "user"


class TestSearch:
    def test_search_by_name_exact(self, tmp_path):
        _create_skill(tmp_path, "weather")
        _create_skill(tmp_path, "weather-forecast")
        _create_skill(tmp_path, "calendar")

        reg = SkillsRegistry(
            sources=[SkillSource(name="t", path=tmp_path, read_only=True)]
        )
        reg.discover()

        results = reg.search("weather")
        assert len(results) == 2
        assert results[0].name == "weather"  # exact match first

    def test_search_by_description(self, tmp_path):
        _create_skill(tmp_path, "skill-1", description="Handles crypto trading automation.")
        _create_skill(tmp_path, "skill-2", description="Weather in Moscow.")

        reg = SkillsRegistry(
            sources=[SkillSource(name="t", path=tmp_path, read_only=True)]
        )
        reg.discover()

        results = reg.search("crypto")
        assert len(results) == 1
        assert results[0].name == "skill-1"

    def test_search_case_insensitive(self, tmp_path):
        _create_skill(tmp_path, "weather")
        reg = SkillsRegistry(
            sources=[SkillSource(name="t", path=tmp_path, read_only=True)]
        )
        reg.discover()

        assert len(reg.search("WEATHER")) == 1
        assert len(reg.search("WeAtHer")) == 1

    def test_empty_query_returns_all(self, tmp_path):
        _create_skill(tmp_path, "a")
        _create_skill(tmp_path, "b")
        reg = SkillsRegistry(
            sources=[SkillSource(name="t", path=tmp_path, read_only=True)]
        )
        reg.discover()
        assert len(reg.search("")) == 2


class TestReload:
    def test_reload_picks_up_new_skills(self, tmp_path):
        _create_skill(tmp_path, "first")
        reg = SkillsRegistry(
            sources=[SkillSource(name="t", path=tmp_path, read_only=True)]
        )
        reg.discover()
        assert len(reg.list_all()) == 1

        _create_skill(tmp_path, "second")
        reg.reload()
        assert len(reg.list_all()) == 2


class TestMalformedSkills:
    def test_skips_malformed_instead_of_crashing(self, tmp_path):
        good = tmp_path / "good-skill"
        good.mkdir()
        (good / "SKILL.md").write_text(
            "---\nname: good-skill\ndescription: Valid skill. Use when good.\n---\n",
            encoding="utf-8",
        )

        bad = tmp_path / "BadName"
        bad.mkdir()
        (bad / "SKILL.md").write_text(
            "---\nname: BadName\ndescription: bad\n---\n",  # uppercase + short
            encoding="utf-8",
        )

        reg = SkillsRegistry(
            sources=[SkillSource(name="t", path=tmp_path, read_only=True)],
            strict=False,  # non-strict: load what we can
        )
        reg.discover()

        # Bad skill loaded non-strictly (logs warning), good skill loaded fine
        assert len(reg.list_all()) >= 1
        assert reg.get("good-skill") is not None
