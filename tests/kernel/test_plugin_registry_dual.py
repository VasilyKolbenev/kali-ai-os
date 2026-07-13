"""Tests for dual-format plugin_registry (SKILL.md + manifest.yaml)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from kernel.plugin_registry import PluginRegistry


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def _make_skill_md(root: Path, name: str, *, allowed_tools: str = "") -> None:
    tools_line = f"allowed-tools: {allowed_tools}\n" if allowed_tools else ""
    _write(
        root / name / "SKILL.md",
        f"""
        ---
        name: {name}
        description: Test skill '{name}' for registry tests. Use when testing.
        {tools_line}---

        # {name}

        Instructions.
        """,
    )


def _make_legacy_manifest(
    root: Path, name: str, *, tools: list[dict] | None = None
) -> None:
    if tools:
        tool_block = "tools:\n"
        for t in tools:
            tool_block += f"  - name: {t['name']}\n"
            tool_block += f"    description: \"{t.get('description', '')}\"\n"
    else:
        tool_block = "tools: []\n"

    content = (
        f"name: {name}\n"
        f'version: "2.5.0"\n'
        f'description: "Legacy {name}"\n'
        f"{tool_block}"
        f"protocol: native\n"
    )
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / "manifest.yaml").write_text(content, encoding="utf-8")


class TestDualDiscovery:
    def test_skill_md_only(self, tmp_path):
        _make_skill_md(tmp_path, "pure-skill", allowed_tools="tool_a tool_b")

        reg = PluginRegistry(tmp_path)
        agents = reg.discover()

        assert len(agents) == 1
        assert agents[0].name == "pure-skill"
        assert agents[0].protocol == "skill"  # no scripts/agent.py → pure skill
        assert [t.name for t in agents[0].tools] == ["tool_a", "tool_b"]
        # SKILL.md manifest is retrievable
        assert reg.get_skill("pure-skill") is not None

    def test_legacy_manifest_only(self, tmp_path):
        _make_legacy_manifest(
            tmp_path, "legacy-only",
            tools=[{"name": "do_thing", "description": "Does a thing"}],
        )

        reg = PluginRegistry(tmp_path)
        agents = reg.discover()

        assert len(agents) == 1
        assert agents[0].name == "legacy-only"
        assert agents[0].version == "2.5.0"
        assert agents[0].protocol == "native"
        # No SKILL.md → skill lookup returns None
        assert reg.get_skill("legacy-only") is None

    def test_both_formats_merge_correctly(self, tmp_path):
        """Legacy tool defs should augment SKILL.md-derived manifest."""
        _make_skill_md(tmp_path, "hybrid", allowed_tools="legacy_tool")
        _make_legacy_manifest(
            tmp_path, "hybrid",
            tools=[{"name": "legacy_tool", "description": "Rich description from legacy"}],
        )

        reg = PluginRegistry(tmp_path)
        agents = reg.discover()

        assert len(agents) == 1
        agent = agents[0]
        # SKILL.md provides name/description; legacy provides rich tool defs
        assert agent.name == "hybrid"
        assert len(agent.tools) == 1
        assert agent.tools[0].description == "Rich description from legacy"
        # SKILL.md version metadata beats legacy version in our mapper when present,
        # but since SKILL.md has no metadata.version, legacy 2.5.0 wins
        assert agent.version == "2.5.0"

    def test_skips_invalid_directories(self, tmp_path):
        _make_skill_md(tmp_path, "good")
        (tmp_path / "empty-dir").mkdir()
        (tmp_path / "_base").mkdir()  # starts with _ → skip
        (tmp_path / ".hidden").mkdir()  # starts with . → skip
        (tmp_path / "orphan.txt").write_text("not a dir")

        reg = PluginRegistry(tmp_path)
        agents = reg.discover()

        assert len(agents) == 1
        assert agents[0].name == "good"


class TestToolExposure:
    def test_tools_namespaced_correctly(self, tmp_path):
        _make_legacy_manifest(
            tmp_path, "weather",
            tools=[{"name": "get_current", "description": "Now"}],
        )

        reg = PluginRegistry(tmp_path)
        reg.discover()

        tools = reg.get_all_tools()
        # The registry always exposes builtin kali__* tools (list_my_agents,
        # added in the 2026-06-25 core-loop sprint) alongside agent tools —
        # assert on the agent's namespaced tool, not an exact count.
        agent_tools = [
            t for t in tools if t["function"]["name"] == "weather__get_current"
        ]
        assert len(agent_tools) == 1
        assert agent_tools[0]["function"]["description"] == "Now"
        assert any(
            t["function"]["name"].startswith("kali__") for t in tools
        ), "builtin kali__* tools must stay exposed"

    def test_find_agent_for_namespaced_tool(self, tmp_path):
        _make_legacy_manifest(
            tmp_path, "math",
            tools=[{"name": "add", "description": "+"}],
        )

        reg = PluginRegistry(tmp_path)
        reg.discover()

        owner = reg.find_agent_for_tool("math__add")
        assert owner is not None
        assert owner.name == "math"

    def test_find_returns_none_for_unknown(self, tmp_path):
        _make_legacy_manifest(
            tmp_path, "x", tools=[{"name": "y", "description": ""}],
        )
        reg = PluginRegistry(tmp_path)
        reg.discover()

        assert reg.find_agent_for_tool("nonexistent__tool") is None
        assert reg.find_agent_for_tool("no_double_underscore") is None


class TestListCategories:
    def test_list_skills_only(self, tmp_path):
        # Pure skill (no scripts)
        _make_skill_md(tmp_path, "pure")
        # Legacy with protocol=native
        _make_legacy_manifest(tmp_path, "native-agent")

        reg = PluginRegistry(tmp_path)
        reg.discover()

        skills = reg.list_skills()
        agents = reg.list_agents_only()

        assert [s.name for s in skills] == ["pure"]
        assert [a.name for a in agents] == ["native-agent"]

    def test_script_equipped_skill_classified_as_native(self, tmp_path):
        """SKILL.md + scripts/agent.py should be treated as native (executable)."""
        _make_skill_md(tmp_path, "with-script")
        (tmp_path / "with-script" / "scripts").mkdir()
        (tmp_path / "with-script" / "scripts" / "agent.py").write_text(
            "# script\n", encoding="utf-8"
        )

        reg = PluginRegistry(tmp_path)
        reg.discover()

        agent = reg.get("with-script")
        assert agent is not None
        assert agent.protocol == "native"  # has executable code
