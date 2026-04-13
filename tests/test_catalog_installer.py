"""Tests for package installer."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from kernel.catalog.installer import install_package


def _make_skill_package(tmp_path: Path) -> Path:
    """Create a test .kali-agent skill package."""
    agent_dir = tmp_path / "src" / "water-tracker"
    agent_dir.mkdir(parents=True)
    (agent_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "water-tracker", "version": "1.0.0",
        "description": "Test", "protocol": "skill",
    }))
    (agent_dir / "skill.yaml").write_text(yaml.dump({
        "template": "tracker", "config": {"unit": "ml"},
    }))
    from kernel.catalog.package import pack
    return pack(agent_dir, tmp_path / "water-tracker.kali-agent")


def _make_agent_package(tmp_path: Path, safe: bool = True) -> Path:
    """Create a test .kali-agent agent package."""
    agent_dir = tmp_path / "src" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "manifest.yaml").write_text(yaml.dump({
        "name": "test-agent", "version": "1.0.0",
        "description": "Test", "protocol": "native",
    }))
    code = 'import json\ndef run(): return {"ok": True}\n'
    if not safe:
        code = 'import subprocess\nsubprocess.call(["rm", "-rf", "/"])\n'
    (agent_dir / "agent.py").write_text(code)
    from kernel.catalog.package import pack
    return pack(agent_dir, tmp_path / "test-agent.kali-agent")


class TestInstaller:
    @pytest.mark.asyncio
    async def test_install_skill(self, tmp_path: Path) -> None:
        pkg = _make_skill_package(tmp_path)
        agents_dir = tmp_path / "agents"
        executor = MagicMock()
        result = await install_package(pkg, agents_dir, skill_executor=executor)
        assert result["status"] == "installed"
        assert result["type"] == "skill"
        executor.load_skill.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_safe_agent(self, tmp_path: Path) -> None:
        pkg = _make_agent_package(tmp_path, safe=True)
        agents_dir = tmp_path / "agents"
        registry = MagicMock()
        registry.get.return_value = MagicMock()
        runtime = AsyncMock()
        result = await install_package(
            pkg, agents_dir, plugin_registry=registry, agent_runtime=runtime,
        )
        assert result["status"] == "installed"

    @pytest.mark.asyncio
    async def test_install_unsafe_agent_blocked(self, tmp_path: Path) -> None:
        pkg = _make_agent_package(tmp_path, safe=False)
        agents_dir = tmp_path / "agents"
        result = await install_package(pkg, agents_dir)
        assert result["status"] == "unsafe"
        assert len(result["issues"]) > 0
        # Verify unsafe agent was cleaned up
        assert not (agents_dir / "test-agent").exists()

    @pytest.mark.asyncio
    async def test_install_bad_package(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.kali-agent"
        bad_file.write_text("not a zip")
        agents_dir = tmp_path / "agents"
        result = await install_package(bad_file, agents_dir)
        assert result["status"] == "error"
