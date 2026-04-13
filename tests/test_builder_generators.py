"""Tests for skill_generator and agent_generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from kernel.builder.skill_generator import generate_skill


# ===========================================================================
# Skill generator tests
# ===========================================================================


def test_generate_skill_creates_directory(tmp_path: Path) -> None:
    generate_skill(
        name="my-tracker",
        template="tracker",
        description="Track my habits",
        config={"unit": "kg"},
        agents_dir=tmp_path,
    )
    assert (tmp_path / "my-tracker").is_dir()


def test_generate_skill_creates_manifest_yaml(tmp_path: Path) -> None:
    generate_skill(
        name="my-tracker",
        template="tracker",
        description="Track my habits",
        config={},
        agents_dir=tmp_path,
    )
    manifest_path = tmp_path / "my-tracker" / "manifest.yaml"
    assert manifest_path.exists()


def test_generate_skill_creates_skill_yaml(tmp_path: Path) -> None:
    generate_skill(
        name="my-tracker",
        template="tracker",
        description="Track my habits",
        config={},
        agents_dir=tmp_path,
    )
    skill_path = tmp_path / "my-tracker" / "skill.yaml"
    assert skill_path.exists()


def test_generate_skill_manifest_has_correct_template(tmp_path: Path) -> None:
    generate_skill(
        name="morning-reminder",
        template="reminder",
        description="Remind me to exercise",
        config={"time": "08:00"},
        agents_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "morning-reminder" / "manifest.yaml").read_text())
    assert manifest["template"] == "reminder"


def test_generate_skill_manifest_name_matches(tmp_path: Path) -> None:
    generate_skill(
        name="server-monitor",
        template="monitor",
        description="Monitor my server",
        config={"url": "https://example.com"},
        agents_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "server-monitor" / "manifest.yaml").read_text())
    assert manifest["name"] == "server-monitor"


def test_generate_skill_manifest_has_tools(tmp_path: Path) -> None:
    generate_skill(
        name="my-logger",
        template="logger",
        description="Keep a diary",
        config={},
        agents_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "my-logger" / "manifest.yaml").read_text())
    assert isinstance(manifest["tools"], list)
    assert len(manifest["tools"]) > 0


def test_generate_skill_tracker_has_correct_tools(tmp_path: Path) -> None:
    generate_skill(
        name="weight-tracker",
        template="tracker",
        description="Track weight",
        config={},
        agents_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "weight-tracker" / "manifest.yaml").read_text())
    tool_names = [t["name"] for t in manifest["tools"]]
    assert "log" in tool_names
    assert "summary" in tool_names
    assert "trend" in tool_names


def test_generate_skill_capabilities_prefixed_with_name(tmp_path: Path) -> None:
    generate_skill(
        name="notifier-test",
        template="notifier",
        description="Alert me",
        config={},
        agents_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "notifier-test" / "manifest.yaml").read_text())
    for cap in manifest["capabilities"]:
        assert cap.startswith("notifier-test.")


def test_generate_skill_config_embedded_in_skill_yaml(tmp_path: Path) -> None:
    cfg = {"threshold": 42, "unit": "celsius"}
    generate_skill(
        name="temp-monitor",
        template="monitor",
        description="Temperature monitor",
        config=cfg,
        agents_dir=tmp_path,
    )
    skill_yaml = yaml.safe_load((tmp_path / "temp-monitor" / "skill.yaml").read_text())
    assert skill_yaml["config"]["threshold"] == 42
    assert skill_yaml["config"]["unit"] == "celsius"


def test_generate_skill_returns_path(tmp_path: Path) -> None:
    result = generate_skill(
        name="my-skill",
        template="tracker",
        description="Test",
        config={},
        agents_dir=tmp_path,
    )
    assert isinstance(result, Path)
    assert result == tmp_path / "my-skill"


def test_generate_skill_unknown_template_uses_default_tools(tmp_path: Path) -> None:
    """Unknown template types fall back to default tools (run + status)."""
    generate_skill(
        name="exotic-skill",
        template="some_unknown_template",
        description="Something exotic",
        config={},
        agents_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "exotic-skill" / "manifest.yaml").read_text())
    tool_names = [t["name"] for t in manifest["tools"]]
    assert "run" in tool_names


# ===========================================================================
# Agent generator tests
# ===========================================================================


def _make_mock_anthropic(response_text: str) -> MagicMock:
    """Build a mock `anthropic` module whose Anthropic() client returns response_text."""
    mock_content = MagicMock()
    mock_content.text = response_text

    mock_message = MagicMock()
    mock_message.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    return mock_anthropic


_SAMPLE_AGENT_CODE = """\
import logging
from typing import Any

from agents._base.agent_base import BaseAgent

logger = logging.getLogger(__name__)


class CustomAgent(BaseAgent):
    def get_name(self) -> str:
        return "test-agent"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "run":
            return {"status": "ok"}
        raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    CustomAgent().run()
"""


def test_generate_agent_writes_agent_py(tmp_path: Path) -> None:
    mock_anthropic = _make_mock_anthropic(_SAMPLE_AGENT_CODE)

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
        patch("kernel.builder.agent_generator.anthropic", mock_anthropic),
    ):
        from kernel.builder.agent_generator import generate_agent

        result = generate_agent(
            name="test-agent",
            description="A test agent",
            tools=[{"name": "run", "description": "Run it"}],
            apis=[],
            agents_dir=tmp_path,
        )

    assert result is not None
    assert (tmp_path / "test-agent" / "agent.py").exists()


def test_generate_agent_writes_manifest_yaml(tmp_path: Path) -> None:
    mock_anthropic = _make_mock_anthropic(_SAMPLE_AGENT_CODE)

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
        patch("kernel.builder.agent_generator.anthropic", mock_anthropic),
    ):
        from kernel.builder.agent_generator import generate_agent

        result = generate_agent(
            name="test-agent",
            description="A test agent",
            tools=[{"name": "run", "description": "Run it"}],
            apis=[],
            agents_dir=tmp_path,
        )

    assert result is not None
    manifest_path = tmp_path / "test-agent" / "manifest.yaml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["name"] == "test-agent"


def test_generate_agent_strips_markdown_fences(tmp_path: Path) -> None:
    fenced_code = f"```python\n{_SAMPLE_AGENT_CODE.strip()}\n```"
    mock_anthropic = _make_mock_anthropic(fenced_code)

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
        patch("kernel.builder.agent_generator.anthropic", mock_anthropic),
    ):
        from kernel.builder.agent_generator import generate_agent

        result = generate_agent(
            name="fenced-agent",
            description="Agent with fenced output",
            tools=[{"name": "run", "description": "Run"}],
            apis=[],
            agents_dir=tmp_path,
        )

    assert result is not None
    written_code = (tmp_path / "fenced-agent" / "agent.py").read_text()
    assert "```" not in written_code


def test_generate_agent_returns_none_without_api_key(tmp_path: Path) -> None:
    import os

    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)

            from kernel.builder.agent_generator import generate_agent

            result = generate_agent(
                name="no-key-agent",
                description="Should fail gracefully",
                tools=[],
                apis=[],
                agents_dir=tmp_path,
            )

        assert result is None
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_generate_agent_returns_none_on_api_error(tmp_path: Path) -> None:
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("Network timeout")

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
        patch("kernel.builder.agent_generator.anthropic", mock_anthropic),
    ):
        from kernel.builder.agent_generator import generate_agent

        result = generate_agent(
            name="error-agent",
            description="Should handle API error",
            tools=[],
            apis=[],
            agents_dir=tmp_path,
        )

    assert result is None


def test_generate_agent_manifest_includes_network_permission_for_apis(tmp_path: Path) -> None:
    mock_anthropic = _make_mock_anthropic(_SAMPLE_AGENT_CODE)

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
        patch("kernel.builder.agent_generator.anthropic", mock_anthropic),
    ):
        from kernel.builder.agent_generator import generate_agent

        result = generate_agent(
            name="api-agent",
            description="Calls external APIs",
            tools=[{"name": "fetch", "description": "Fetch data"}],
            apis=["openweather", "telegram"],
            agents_dir=tmp_path,
        )

    assert result is not None
    manifest = yaml.safe_load((tmp_path / "api-agent" / "manifest.yaml").read_text())
    assert "network" in manifest["permissions"]
