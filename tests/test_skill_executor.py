"""Tests for Skill Engine."""

import pytest
from kernel.models import AgentManifest


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
