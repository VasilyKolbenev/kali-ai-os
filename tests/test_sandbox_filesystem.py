"""Tests for filesystem sandbox in BaseAgent."""

import json
import pytest
from pathlib import Path
from agents._base.agent_base import BaseAgent
from typing import Any


class StubAgent(BaseAgent):
    """Minimal agent for testing."""

    def get_name(self) -> str:
        return "stub"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return {}


class TestFilesystemSandbox:
    @pytest.fixture
    def agent(self, tmp_path: Path) -> StubAgent:
        a = StubAgent.__new__(StubAgent)
        a._data_dir = tmp_path / "data" / "agents" / "stub"
        a._data_dir.mkdir(parents=True, exist_ok=True)
        a._start_time = 0
        a._config = {}
        return a

    def test_normal_save_load(self, agent: StubAgent) -> None:
        agent._save_json("state.json", {"count": 1})
        assert agent._load_json("state.json") == {"count": 1}

    def test_load_missing_returns_none(self, agent: StubAgent) -> None:
        assert agent._load_json("nonexistent.json") is None

    def test_path_traversal_dotdot_rejected(self, agent: StubAgent) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            agent._save_json("../../etc/passwd", {"x": 1})

    def test_path_traversal_slash_rejected(self, agent: StubAgent) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            agent._save_json("other/data.json", {"x": 1})

    def test_path_traversal_backslash_rejected(self, agent: StubAgent) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            agent._save_json("..\\system32", {"x": 1})

    def test_load_traversal_rejected(self, agent: StubAgent) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            agent._load_json("../secret.json")
