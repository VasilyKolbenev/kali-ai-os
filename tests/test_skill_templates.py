"""Tests for skill templates."""

import pytest
from pathlib import Path
from kernel.skill_templates.base import SkillTemplate
from typing import Any


class FakeTemplate(SkillTemplate):
    """Concrete template for testing."""

    @property
    def template_name(self) -> str:
        return "fake"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "ping":
            return {"pong": True}
        return {"error": f"Unknown action: {action}"}


class TestSkillTemplateStorage:
    @pytest.fixture
    def template(self, tmp_path):
        return FakeTemplate(skill_name="test-skill", data_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_save_and_load_data(self, template):
        """Template can persist and retrieve JSON data."""
        await template.save_data("state.json", {"count": 42})
        loaded = await template.load_data("state.json")
        assert loaded == {"count": 42}

    @pytest.mark.asyncio
    async def test_load_missing_returns_default(self, template):
        """Loading non-existent file returns default."""
        loaded = await template.load_data("missing.json", default=[])
        assert loaded == []

    @pytest.mark.asyncio
    async def test_execute_action(self, template):
        """Template executes actions correctly."""
        result = await template.execute("ping", {}, {})
        assert result == {"pong": True}

    @pytest.mark.asyncio
    async def test_data_isolated_per_skill(self, tmp_path):
        """Each skill gets its own data directory."""
        t1 = FakeTemplate(skill_name="skill-a", data_dir=tmp_path)
        t2 = FakeTemplate(skill_name="skill-b", data_dir=tmp_path)
        await t1.save_data("val.json", {"x": 1})
        await t2.save_data("val.json", {"x": 2})
        assert await t1.load_data("val.json") == {"x": 1}
        assert await t2.load_data("val.json") == {"x": 2}
