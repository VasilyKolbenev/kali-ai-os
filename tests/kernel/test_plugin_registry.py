"""Tests for agent plugin registry."""

from pathlib import Path

import pytest
import yaml

from kernel.plugin_registry import PluginRegistry


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    cal_dir = tmp_path / "calendar"
    cal_dir.mkdir()
    (cal_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "calendar",
                "version": "1.0.0",
                "description": "Calendar agent",
                "capabilities": ["calendar.read", "calendar.write"],
                "tools": [{"name": "get_events", "description": "Get events", "parameters": {}}],
                "protocol": "native",
                "permissions": ["network"],
            }
        )
    )

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "tasks",
                "version": "1.0.0",
                "description": "Tasks agent",
                "capabilities": ["tasks.read", "tasks.write"],
                "protocol": "native",
            }
        )
    )

    return tmp_path


@pytest.fixture
def registry(agents_dir: Path) -> PluginRegistry:
    return PluginRegistry(agents_dir)


class TestPluginRegistry:
    def test_discover_agents(self, registry: PluginRegistry) -> None:
        agents = registry.discover()
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"calendar", "tasks"}

    def test_get_agent_by_name(self, registry: PluginRegistry) -> None:
        registry.discover()
        agent = registry.get("calendar")
        assert agent is not None
        assert agent.name == "calendar"

    def test_get_missing_agent_returns_none(self, registry: PluginRegistry) -> None:
        registry.discover()
        assert registry.get("nonexistent") is None

    def test_get_all_tools(self, registry: PluginRegistry) -> None:
        registry.discover()
        tools = registry.get_all_tools()
        names = {t["function"]["name"] for t in tools}
        assert "calendar__get_events" in names
        # The built-in "list my agents" tool is always offered to the LLM so a
        # "what agents do I have" query has a real tool to call (core-loop 2b).
        assert "kali__list_my_agents" in names

    def test_find_agent_by_tool_name(self, registry: PluginRegistry) -> None:
        registry.discover()
        agent = registry.find_agent_for_tool("calendar__get_events")
        assert agent is not None
        assert agent.name == "calendar"

    def test_skip_invalid_manifest(self, agents_dir: Path) -> None:
        bad_dir = agents_dir / "broken"
        bad_dir.mkdir()
        (bad_dir / "manifest.yaml").write_text("not: valid: yaml: [")

        registry = PluginRegistry(agents_dir)
        agents = registry.discover()
        assert len(agents) == 2

    def test_skip_dir_without_manifest(self, agents_dir: Path) -> None:
        (agents_dir / "no_manifest").mkdir()
        registry = PluginRegistry(agents_dir)
        agents = registry.discover()
        assert len(agents) == 2

    def test_list_registered(self, registry: PluginRegistry) -> None:
        registry.discover()
        registered = registry.list_registered()
        assert len(registered) == 2

    def test_register_dir_adds_single_skill_live(self, registry: PluginRegistry) -> None:
        """A freshly-deployed skill becomes callable without a full re-scan and
        without disturbing already-registered agents (M2.2 consent safety)."""
        registry.discover()
        assert registry.get("water-tracker") is None

        skill_dir = registry.agents_dir / "water-tracker"
        skill_dir.mkdir()
        (skill_dir / "manifest.yaml").write_text(
            yaml.dump(
                {
                    "name": "water-tracker",
                    "version": "1.0.0",
                    "description": "Track water",
                    "protocol": "skill",
                    "tools": [{"name": "log", "description": "Log a data point", "parameters": {}}],
                    "capabilities": ["water-tracker.log"],
                    "permissions": [],
                }
            )
        )
        (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))

        manifest = registry.register_dir(skill_dir)
        assert manifest is not None and manifest.name == "water-tracker"
        # Now live: get() finds it and its tool is offered to the LLM.
        assert registry.get("water-tracker") is not None
        tool_names = {t["function"]["name"] for t in registry.get_all_tools()}
        assert "water-tracker__log" in tool_names
        # Existing agents untouched (no full re-scan, consent state preserved).
        assert registry.get("calendar") is not None
        assert registry.get("tasks") is not None

    def test_register_dir_ignores_non_skill_dir(self, registry: PluginRegistry) -> None:
        registry.discover()
        empty = registry.agents_dir / "empty"
        empty.mkdir()
        assert registry.register_dir(empty) is None


def _write_voice_skill(skill_dir: Path) -> None:
    """A voice-built skill on disk: manifest.yaml + skill.yaml, NO SKILL.md."""
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": skill_dir.name,
                "version": "1.0.0",
                "description": "Track water intake",
                "protocol": "skill",
                "tools": [{"name": "log", "description": "Log a data point", "parameters": {}}],
                "capabilities": [f"{skill_dir.name}.log"],
                "permissions": [],
            }
        )
    )
    (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))


def test_skill_installed_outside_agents_dir_is_callable(tmp_path: Path) -> None:
    """A skill registered from %APPDATA%/KALI/skills (NOT agents_dir) must still
    enter the LLM tool palette — the registry-reconciliation fix."""
    reg = PluginRegistry(tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    install_dir = tmp_path / "appdata_skills" / "water-tracker"
    _write_voice_skill(install_dir)

    assert reg.register_dir(install_dir) is not None
    tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
    assert "water-tracker__log" in tool_names
    assert reg.skill_dir_for("water-tracker") == install_dir


def test_skill_without_skill_yaml_is_withheld(tmp_path: Path) -> None:
    """Withhold-guard preserved: a protocol='skill' manifest with no skill.yaml
    anywhere must NOT be advertised (calling it would yield 'Skill not found')."""
    reg = PluginRegistry(tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    bad = tmp_path / "appdata_skills" / "ghost"
    bad.mkdir(parents=True)
    (bad / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "ghost", "version": "1.0.0", "description": "no template",
                "protocol": "skill",
                "tools": [{"name": "run", "description": "r", "parameters": {}}],
                "capabilities": ["ghost.run"], "permissions": [],
            }
        )
    )  # deliberately NO skill.yaml

    assert reg.register_dir(bad) is not None  # present in /agents...
    tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
    assert "ghost__run" not in tool_names  # ...but withheld from the LLM
