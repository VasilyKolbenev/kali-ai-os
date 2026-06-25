"""Tests for deployer."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from kernel.builder.deployer import deploy_skill, deploy_agent


class TestDeploySkill:
    @pytest.fixture
    def skill_dir(self, tmp_path):
        d = tmp_path / "agents" / "test-skill"
        d.mkdir(parents=True)
        (d / "manifest.yaml").write_text(yaml.dump({
            "name": "test-skill", "version": "1.0.0",
            "description": "Test", "protocol": "skill",
        }))
        (d / "skill.yaml").write_text(yaml.dump({
            "template": "tracker", "config": {"unit": "ml", "daily_goal": 2000},
        }))
        return d

    @pytest.mark.asyncio
    async def test_deploy_skill_success(self, skill_dir):
        executor = MagicMock()
        result = await deploy_skill(skill_dir, executor)
        assert result["status"] == "deployed"
        executor.load_skill.assert_called_once_with(skill_dir)

    @pytest.mark.asyncio
    async def test_deploy_skill_failure(self, skill_dir):
        executor = MagicMock()
        executor.load_skill.side_effect = FileNotFoundError("no skill.yaml")
        result = await deploy_skill(skill_dir, executor)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_deploy_skill_registers_cron(self, skill_dir):
        executor = MagicMock()
        executor.get_skill_info.return_value = {
            "config": {"reminders": {"enabled": True, "interval_hours": 2}},
        }
        scheduler = MagicMock()
        result = await deploy_skill(skill_dir, executor, scheduler)
        assert result["status"] == "deployed"
        scheduler.register_cron.assert_called_once()


class TestBuilderFlowRegistersSkill:
    @pytest.mark.asyncio
    async def test_deploy_registers_skill_live(self, tmp_path):
        """deploy() must register the new skill in the plugin registry so the
        assistant can find/call it without a restart (core-loop fix 2a)."""
        from unittest.mock import MagicMock

        from kernel.builder.flow import BuilderFlow
        from kernel.builder.session_store import SessionStore

        store = SessionStore()
        executor = MagicMock()
        registry = MagicMock()
        flow = BuilderFlow(
            session_store=store,
            agents_dir=tmp_path,
            skill_executor=executor,
            plugin_registry=registry,
        )
        sid = store.create(request="track water", intent_type="skill", template="tracker")
        store.get(sid).spec = {
            "name": "water-tracker",
            "template": "tracker",
            "description": "track water",
            "config": {},
        }

        result = await flow.deploy(sid)

        assert result["status"] == "deployed"
        registry.register_dir.assert_called_once()


class TestDeployAgent:
    @pytest.mark.asyncio
    async def test_deploy_agent_success(self, tmp_path):
        agent_dir = tmp_path / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        registry = MagicMock()
        registry.get.return_value = MagicMock()
        runtime = AsyncMock()
        result = await deploy_agent(agent_dir, registry, runtime)
        assert result["status"] == "deployed"

    @pytest.mark.asyncio
    async def test_deploy_agent_missing_manifest(self, tmp_path):
        agent_dir = tmp_path / "agents" / "bad"
        agent_dir.mkdir(parents=True)
        registry = MagicMock()
        registry.get.return_value = None
        runtime = AsyncMock()
        result = await deploy_agent(agent_dir, registry, runtime)
        assert result["status"] == "error"
