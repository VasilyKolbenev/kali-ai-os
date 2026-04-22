"""Tests for SkillsCatalog — remote GitHub skills aggregator."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kernel.skills.catalog import (
    CatalogEntry,
    CatalogFetchError,
    CatalogSource,
    SkillsCatalog,
    DEFAULT_SOURCES,
)


def _make_source(**overrides) -> CatalogSource:
    base = dict(
        id="test", label="Test", owner="acme", repo="skills",
        ref="main", skills_path="skills", trust="community",
    )
    base.update(overrides)
    return CatalogSource(**base)


# Sample GitHub tree response
_SAMPLE_TREE = {
    "tree": [
        {"path": "README.md", "type": "blob"},
        {"path": "skills/weather/SKILL.md", "type": "blob"},
        {"path": "skills/weather/scripts/main.py", "type": "blob"},
        {"path": "skills/todo-list/SKILL.md", "type": "blob"},
        {"path": "skills/outside-prefix/SKILL.md", "type": "blob"},  # inside "skills/" → kept
        {"path": "not-skills/bad/SKILL.md", "type": "blob"},  # outside prefix → skip
        {"path": "skills/empty-dir", "type": "tree"},  # not a blob → skip
    ]
}

_SAMPLE_SKILL_MD = """---
name: weather
description: Weather lookups. Use when the user asks for forecasts.
license: MIT
---

# Weather skill

Body.
"""

_SAMPLE_TODO_MD = """---
name: todo-list
description: Manages a personal to-do list. Use when user mentions tasks.
metadata:
  version: "1.0"
---

# Todo
"""


class TestDefaultSources:
    def test_defaults_include_key_sources(self):
        source_ids = {s.id for s in DEFAULT_SOURCES}
        assert "anthropic" in source_ids
        assert "microsoft" in source_ids
        assert "voltagent" in source_ids
        assert "kali" in source_ids

    def test_anthropic_marked_official(self):
        a = next(s for s in DEFAULT_SOURCES if s.id == "anthropic")
        assert a.trust == "official"

    def test_kali_marked_verified(self):
        k = next(s for s in DEFAULT_SOURCES if s.id == "kali")
        assert k.trust == "verified"

    def test_neuraldeep_is_aggregator(self):
        nd = next(s for s in DEFAULT_SOURCES if s.id == "neuraldeep")
        assert nd.source_type == "aggregator_json"
        assert nd.api_url == "https://neuraldeep.ru/api/skills"
        assert nd.trust == "community"


class TestAggregatorSource:
    """Tests for aggregator_json source type (e.g. NeuralDeep)."""

    _SAMPLE_API = [
        {
            "id": "uuid-1",
            "name": "yandex-wordstat",
            "owner": "artwist-polyakov",
            "repo": "polyakov-claude-skills",
            "description": "Яндекс Wordstat — поиск и анализ ключевых слов.",
            "contentPath": "yandex-wordstat",
            "category": "маркетинг",
            "tags": ["яндекс", "маркетинг", "российские сервисы"],
            "installs": 42,
            "githubStars": 12,
            "featured": True,
        },
        {
            "id": "uuid-2",
            "name": "1c-enterprise-skills",
            "owner": "Nikolay-Shirokov",
            "repo": "cc-1c-skills",
            "description": "Разработка на 1С:Предприятие 8.3.",
            "contentPath": None,
            "category": "утилиты",
            "tags": ["1с", "1c"],
            "installs": 122,
        },
        # Malformed entry — missing owner — should be skipped
        {
            "name": "broken",
            "description": "no owner or repo",
        },
    ]

    def test_fetches_and_normalizes(self, tmp_path):
        source = CatalogSource(
            id="nd",
            label="NeuralDeep",
            source_type="aggregator_json",
            api_url="https://neuraldeep.ru/api/skills",
            trust="community",
        )
        responses = {
            "https://neuraldeep.ru/api/skills": {"json": self._SAMPLE_API},
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("nd", force=True)

        # Two valid entries, one malformed skipped
        assert len(entries) == 2
        by_name = {e.name: e for e in entries}

        wordstat = by_name["yandex-wordstat"]
        assert wordstat.repo_owner == "artwist-polyakov"
        assert wordstat.repo_name == "polyakov-claude-skills"
        assert wordstat.skill_path == "yandex-wordstat"
        assert wordstat.metadata["category"] == "маркетинг"
        assert "яндекс" in wordstat.metadata["tags"]
        assert wordstat.metadata["featured"] is True

        # contentPath=None → skill_path empty (repo root)
        onec = by_name["1c-enterprise-skills"]
        assert onec.skill_path == ""
        assert onec.metadata["installs"] == 122

    def test_missing_api_url_raises(self, tmp_path):
        source = CatalogSource(
            id="bad",
            label="Broken",
            source_type="aggregator_json",
            api_url=None,
        )
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        entries = catalog.refresh_source("bad", force=True)
        # refresh_source swallows CatalogFetchError and returns empty
        assert entries == []

    def test_non_list_response_rejected(self, tmp_path):
        source = CatalogSource(
            id="nd",
            label="NeuralDeep",
            source_type="aggregator_json",
            api_url="https://example.com/skills",
        )
        responses = {
            "https://example.com/skills": {"json": {"error": "not a list"}},
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("nd", force=True)
        assert entries == []


class TestCatalogEntry:
    def test_raw_url_constructed(self):
        entry = CatalogEntry(
            name="x", description="y",
            source_id="s", source_label="S", trust="community",
            repo_owner="acme", repo_name="r", repo_ref="main",
            skill_path="skills/x",
        )
        assert entry.raw_skill_md_url == (
            "https://raw.githubusercontent.com/acme/r/main/skills/x/SKILL.md"
        )

    def test_web_url_constructed(self):
        entry = CatalogEntry(
            name="x", description="y",
            source_id="s", source_label="S", trust="community",
            repo_owner="acme", repo_name="r", repo_ref="main",
            skill_path="skills/x",
        )
        assert entry.web_url == "https://github.com/acme/r/tree/main/skills/x"

    def test_to_dict_includes_urls(self):
        entry = CatalogEntry(
            name="x", description="y",
            source_id="s", source_label="S", trust="community",
            repo_owner="acme", repo_name="r", repo_ref="main",
            skill_path="skills/x",
        )
        d = entry.to_dict()
        assert "raw_skill_md_url" in d
        assert "web_url" in d


def _mock_requests_get(urls_to_responses: dict):
    """Return a function that MagicMocks requests.get with custom responses per URL."""
    def fake_get(url, **kwargs):
        response = MagicMock()
        if url in urls_to_responses:
            data = urls_to_responses[url]
            response.status_code = data.get("status", 200)
            response.text = data.get("text", "")
            if "json" in data:
                response.json = MagicMock(return_value=data["json"])
        else:
            response.status_code = 404
            response.text = f"mock: no stub for {url}"
        return response
    return fake_get


class TestFetchSource:
    def test_successful_fetch(self, tmp_path):
        source = _make_source()
        tree_url = (
            "https://api.github.com/repos/acme/skills/git/trees/main?recursive=1"
        )
        weather_url = (
            "https://raw.githubusercontent.com/acme/skills/main/skills/weather/SKILL.md"
        )
        todo_url = (
            "https://raw.githubusercontent.com/acme/skills/main/skills/todo-list/SKILL.md"
        )
        outside_url = (
            "https://raw.githubusercontent.com/acme/skills/main/skills/outside-prefix/SKILL.md"
        )

        responses = {
            tree_url: {"json": _SAMPLE_TREE},
            weather_url: {"text": _SAMPLE_SKILL_MD},
            todo_url: {"text": _SAMPLE_TODO_MD},
            outside_url: {
                "text": "---\nname: outside-prefix\ndescription: Valid skill.\n---\n"
            },
        }

        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("test", force=True)

        assert len(entries) == 3  # weather + todo + outside-prefix, NOT not-skills/bad
        names = {e.name for e in entries}
        assert names == {"weather", "todo-list", "outside-prefix"}

        w = next(e for e in entries if e.name == "weather")
        assert w.source_id == "test"
        assert w.trust == "community"
        assert w.license == "MIT"

    def test_rate_limit_raises(self, tmp_path):
        source = _make_source()
        responses = {
            f"https://api.github.com/repos/acme/skills/git/trees/main?recursive=1": {
                "status": 403,
                "text": "rate limit exceeded",
            },
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("test", force=True)
        # Rate limit → refresh returns empty list (not raises)
        assert entries == []

    def test_404_raises(self, tmp_path):
        source = _make_source(owner="no", repo="such")
        responses = {
            f"https://api.github.com/repos/no/such/git/trees/main?recursive=1": {
                "status": 404, "text": "Not found",
            },
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("test", force=True)
        assert entries == []

    def test_unknown_source_raises(self, tmp_path):
        catalog = SkillsCatalog(sources=[_make_source()], cache_dir=tmp_path)
        with pytest.raises(ValueError, match="Unknown"):
            catalog.refresh_source("nonexistent")


class TestCache:
    def test_cached_results_reused(self, tmp_path):
        # Prepare cache file with pre-baked data
        cache_file = tmp_path / "test.json"
        cache_file.write_text(json.dumps({
            "cached_at": time.time(),
            "entries": [
                {
                    "name": "cached-skill",
                    "description": "From cache",
                    "source_id": "test",
                    "source_label": "Test",
                    "trust": "community",
                    "repo_owner": "acme",
                    "repo_name": "skills",
                    "repo_ref": "main",
                    "skill_path": "skills/cached-skill",
                    "license": None,
                    "compatibility": None,
                    "metadata": {},
                }
            ],
        }), encoding="utf-8")

        catalog = SkillsCatalog(sources=[_make_source()], cache_dir=tmp_path)
        # No mock — if cache is used, no HTTP call
        entries = catalog.refresh_source("test")
        assert len(entries) == 1
        assert entries[0].name == "cached-skill"

    def test_expired_cache_ignored(self, tmp_path):
        cache_file = tmp_path / "test.json"
        cache_file.write_text(json.dumps({
            "cached_at": 0,  # ancient
            "entries": [{"name": "old", "description": "stale",
                        "source_id": "test", "source_label": "Test", "trust": "community",
                        "repo_owner": "a", "repo_name": "b", "repo_ref": "main",
                        "skill_path": "x", "license": None, "compatibility": None,
                        "metadata": {}}],
        }), encoding="utf-8")

        source = _make_source()
        responses = {
            f"https://api.github.com/repos/acme/skills/git/trees/main?recursive=1": {
                "json": {"tree": []},
            },
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("test")

        # Stale cache discarded → refetched from empty tree → 0 entries
        assert entries == []

    def test_force_bypasses_cache(self, tmp_path):
        cache_file = tmp_path / "test.json"
        cache_file.write_text(json.dumps({
            "cached_at": time.time(),
            "entries": [{"name": "cached", "description": "d",
                        "source_id": "test", "source_label": "Test", "trust": "community",
                        "repo_owner": "a", "repo_name": "b", "repo_ref": "main",
                        "skill_path": "x", "license": None, "compatibility": None,
                        "metadata": {}}],
        }), encoding="utf-8")

        source = _make_source()
        responses = {
            f"https://api.github.com/repos/acme/skills/git/trees/main?recursive=1": {
                "json": {"tree": []},
            },
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("test", force=True)
        assert entries == []


class TestSearch:
    def test_search_across_sources(self, tmp_path):
        catalog = SkillsCatalog(sources=[], cache_dir=tmp_path)
        catalog._entries = {
            "s1": [
                CatalogEntry(
                    name="weather-forecast", description="Forecast tool",
                    source_id="s1", source_label="S1", trust="official",
                    repo_owner="a", repo_name="b", repo_ref="main",
                    skill_path="x",
                ),
            ],
            "s2": [
                CatalogEntry(
                    name="todo", description="tracks user tasks and reminders",
                    source_id="s2", source_label="S2", trust="community",
                    repo_owner="c", repo_name="d", repo_ref="main",
                    skill_path="y",
                ),
            ],
        }
        catalog._sources = [
            _make_source(id="s1", trust="official"),
            _make_source(id="s2", trust="community"),
        ]

        assert len(catalog.search("forecast")) == 1
        assert len(catalog.search("TASKS")) == 1  # case-insensitive description match
        assert len(catalog.search("")) == 2

    def test_sort_by_trust_then_name(self, tmp_path):
        catalog = SkillsCatalog(sources=[], cache_dir=tmp_path)
        catalog._sources = [
            _make_source(id="community-src", trust="community"),
            _make_source(id="official-src", trust="official"),
        ]
        catalog._entries = {
            "community-src": [
                CatalogEntry(
                    name="a-community", description="d",
                    source_id="community-src", source_label="C", trust="community",
                    repo_owner="x", repo_name="y", repo_ref="main", skill_path="z",
                ),
            ],
            "official-src": [
                CatalogEntry(
                    name="z-official", description="d",
                    source_id="official-src", source_label="O", trust="official",
                    repo_owner="x", repo_name="y", repo_ref="main", skill_path="z",
                ),
            ],
        }
        ordered = catalog.list_all()
        assert ordered[0].name == "z-official"  # official first despite later name
        assert ordered[1].name == "a-community"


class TestMetadataExtraction:
    def test_skill_with_metadata_parsed(self, tmp_path):
        source = _make_source()
        tree_url = (
            "https://api.github.com/repos/acme/skills/git/trees/main?recursive=1"
        )
        md_url = (
            "https://raw.githubusercontent.com/acme/skills/main/skills/todo-list/SKILL.md"
        )
        responses = {
            tree_url: {"json": {"tree": [
                {"path": "skills/todo-list/SKILL.md", "type": "blob"},
            ]}},
            md_url: {"text": _SAMPLE_TODO_MD},
        }
        catalog = SkillsCatalog(sources=[source], cache_dir=tmp_path)
        with patch(
            "kernel.skills.catalog.requests.get",
            side_effect=_mock_requests_get(responses),
        ):
            entries = catalog.refresh_source("test", force=True)
        assert len(entries) == 1
        assert entries[0].metadata == {"version": "1.0"}
