"""Shared test fixtures."""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def sample_agents_dir(tmp_path: Path) -> Path:
    """Create a temp agents directory with a test agent."""
    agent_dir = tmp_path / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "test-agent",
                "version": "1.0.0",
                "description": "Test agent",
                "capabilities": ["test.hello"],
                "tools": [{"name": "greet", "description": "Say hi", "parameters": {}}],
                "protocol": "native",
            }
        )
    )
    return tmp_path / "agents"


@pytest.fixture
def sample_config_path(tmp_path: Path) -> Path:
    """Create a temp config file."""
    config_path = tmp_path / "jarvis.yaml"
    config_path.write_text(yaml.dump({"server": {"port": 8000}}))
    return config_path
