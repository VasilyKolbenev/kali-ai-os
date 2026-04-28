"""Shared test fixtures."""

import os
from pathlib import Path

import pytest
import yaml

# Skip the voice-engine prewarm (F5-TTS + Whisper STT) when the FastAPI
# `lifespan` runs inside test fixtures. Without this, every test that
# instantiates `create_app()` pays the ~3-5s ML-model cold-load cost
# per fixture scope — kills CI throughput. See kernel/main.py lifespan.
os.environ.setdefault("KALI_SKIP_PREWARM", "1")


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
    config_path = tmp_path / "kali.yaml"
    config_path.write_text(yaml.dump({"server": {"port": 3005}}))
    return config_path
