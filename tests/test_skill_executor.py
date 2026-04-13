"""Tests for Skill Engine."""

import pytest
import yaml
from pathlib import Path
from kernel.models import AgentManifest
from kernel.skill_executor import SkillExecutor


class TestSkillProtocol:
    def test_skill_protocol_is_valid(self):
        """AgentManifest accepts 'skill' as valid protocol."""
        manifest = AgentManifest(
            name="test-skill",
            version="1.0.0",
            description="Test skill",
            protocol="skill",
        )
        assert manifest.protocol == "skill"

    def test_invalid_protocol_still_rejected(self):
        """Unknown protocols are still rejected."""
        with pytest.raises(ValueError, match="Protocol must be one of"):
            AgentManifest(
                name="bad",
                version="1.0.0",
                description="Bad",
                protocol="invalid",
            )


@pytest.fixture
def skills_dir(tmp_path):
    """Create a test skill directory with manifest + skill.yaml."""
    skill_dir = tmp_path / "agents" / "water-tracker"
    skill_dir.mkdir(parents=True)
    manifest = {
        "name": "water-tracker",
        "version": "1.0.0",
        "description": "Track water intake",
        "protocol": "skill",
        "tools": [
            {"name": "log", "description": "Log intake", "parameters": {"amount": {"type": "number"}}},
            {"name": "summary", "description": "Daily summary", "parameters": {}},
        ],
        "permissions": ["storage", "notifications"],
    }
    (skill_dir / "manifest.yaml").write_text(yaml.dump(manifest))
    skill_config = {
        "template": "tracker",
        "display_name": "Трекер воды",
        "config": {"unit": "мл", "daily_goal": 2000},
    }
    (skill_dir / "skill.yaml").write_text(yaml.dump(skill_config))
    return tmp_path


class TestSkillExecutor:
    @pytest.fixture
    def executor(self, skills_dir):
        return SkillExecutor(data_dir=skills_dir / "data")

    def test_load_skill(self, executor, skills_dir):
        executor.load_skill(skills_dir / "agents" / "water-tracker")
        assert "water-tracker" in executor.list_skills()

    @pytest.mark.asyncio
    async def test_execute_skill_action(self, executor, skills_dir):
        executor.load_skill(skills_dir / "agents" / "water-tracker")
        result = await executor.execute("water-tracker", "log", {"amount": 500})
        # TrackerTemplate.log returns {"date", "total", "unit"}
        assert result["total"] == 500
        assert result["unit"] == "мл"

    @pytest.mark.asyncio
    async def test_execute_unknown_skill_raises(self, executor):
        with pytest.raises(ValueError, match="not found"):
            await executor.execute("nonexistent", "log", {})

    def test_get_skill_info(self, executor, skills_dir):
        executor.load_skill(skills_dir / "agents" / "water-tracker")
        info = executor.get_skill_info("water-tracker")
        assert info["template"] == "tracker"
        assert info["display_name"] == "Трекер воды"

    def test_unload_skill(self, executor, skills_dir):
        executor.load_skill(skills_dir / "agents" / "water-tracker")
        assert executor.unload_skill("water-tracker") is True
        assert "water-tracker" not in executor.list_skills()

    def test_load_skill_missing_yaml_raises(self, executor, tmp_path):
        empty_dir = tmp_path / "agents" / "empty-skill"
        empty_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            executor.load_skill(empty_dir)

    def test_load_skill_unknown_template_raises(self, skills_dir):
        skill_dir = skills_dir / "agents" / "bad-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "nonexistent"}))
        executor = SkillExecutor(data_dir=skills_dir / "data")
        with pytest.raises(ValueError, match="Unknown template"):
            executor.load_skill(skill_dir)

    def test_get_skill_info_unknown_returns_none(self, executor):
        assert executor.get_skill_info("ghost") is None

    def test_unload_nonexistent_returns_false(self, executor):
        assert executor.unload_skill("ghost") is False
