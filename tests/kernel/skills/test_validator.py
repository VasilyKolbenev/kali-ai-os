"""Tests for Agent Skills spec validator."""

from __future__ import annotations

import pytest

from kernel.skills.validator import validate_frontmatter


class TestNameValidation:
    def test_valid_simple_name(self):
        r = validate_frontmatter({"name": "weather", "description": "A skill. Use when needed."})
        assert r.valid
        assert not r.errors

    def test_valid_with_hyphens(self):
        r = validate_frontmatter({"name": "water-tracker", "description": "Track water. Use daily."})
        assert r.valid

    def test_valid_with_digits(self):
        r = validate_frontmatter({"name": "web3-scanner", "description": "Scans web3. Use for crypto."})
        assert r.valid

    def test_reject_uppercase(self):
        r = validate_frontmatter({"name": "Weather", "description": "x"})
        assert not r.valid
        assert any("lowercase" in e for e in r.errors)

    def test_reject_leading_hyphen(self):
        r = validate_frontmatter({"name": "-weather", "description": "x"})
        assert not r.valid
        assert any("start with a hyphen" in e for e in r.errors)

    def test_reject_trailing_hyphen(self):
        r = validate_frontmatter({"name": "weather-", "description": "x"})
        assert not r.valid
        assert any("end with a hyphen" in e for e in r.errors)

    def test_reject_consecutive_hyphens(self):
        r = validate_frontmatter({"name": "bad--name", "description": "x"})
        assert not r.valid
        assert any("consecutive hyphens" in e for e in r.errors)

    def test_reject_empty_name(self):
        r = validate_frontmatter({"name": "", "description": "x"})
        assert not r.valid

    def test_reject_too_long_name(self):
        long_name = "a" * 65
        r = validate_frontmatter({"name": long_name, "description": "x"})
        assert not r.valid
        assert any("64 characters" in e for e in r.errors)

    def test_reject_non_string_name(self):
        r = validate_frontmatter({"name": 123, "description": "x"})
        assert not r.valid


class TestDescriptionValidation:
    def test_valid_description(self):
        r = validate_frontmatter(
            {"name": "x", "description": "A meaningful description that explains when to use this skill."}
        )
        assert r.valid

    def test_reject_empty_description(self):
        r = validate_frontmatter({"name": "x", "description": ""})
        assert not r.valid

    def test_reject_whitespace_description(self):
        r = validate_frontmatter({"name": "x", "description": "   \n\t  "})
        assert not r.valid

    def test_reject_too_long_description(self):
        r = validate_frontmatter({"name": "x", "description": "a" * 1025})
        assert not r.valid
        assert any("1024 characters" in e for e in r.errors)

    def test_warn_very_short_description(self):
        r = validate_frontmatter({"name": "x", "description": "Short."})
        assert r.valid
        assert any("very short" in w for w in r.warnings)


class TestOptionalFields:
    def test_license_valid(self):
        r = validate_frontmatter(
            {"name": "x", "description": "desc with enough chars to pass", "license": "MIT"}
        )
        assert r.valid

    def test_license_rejects_non_string(self):
        r = validate_frontmatter(
            {"name": "x", "description": "desc with enough chars to pass", "license": 42}
        )
        assert not r.valid

    def test_compatibility_length_limit(self):
        r = validate_frontmatter({
            "name": "x",
            "description": "desc with enough chars to pass",
            "compatibility": "a" * 501,
        })
        assert not r.valid

    def test_metadata_valid(self):
        r = validate_frontmatter({
            "name": "x",
            "description": "desc with enough chars to pass",
            "metadata": {"author": "kali", "version": "1.0"},
        })
        assert r.valid

    def test_metadata_rejects_non_dict(self):
        r = validate_frontmatter({
            "name": "x",
            "description": "desc with enough chars to pass",
            "metadata": ["bad", "list"],
        })
        assert not r.valid

    def test_allowed_tools_valid(self):
        r = validate_frontmatter({
            "name": "x",
            "description": "desc with enough chars to pass",
            "allowed-tools": "Read Write Bash(git:*)",
        })
        assert r.valid


class TestDirectoryMatching:
    def test_name_matches_directory(self):
        r = validate_frontmatter(
            {"name": "weather", "description": "desc with enough chars to pass"},
            expected_name="weather",
        )
        assert r.valid

    def test_name_mismatch_flagged(self):
        r = validate_frontmatter(
            {"name": "weather", "description": "desc with enough chars to pass"},
            expected_name="climate",
        )
        assert not r.valid
        assert any("does not match" in e for e in r.errors)


class TestUnknownFields:
    def test_unknown_field_warning(self):
        r = validate_frontmatter({
            "name": "x",
            "description": "desc with enough chars to pass",
            "custom_field": "value",
        })
        assert r.valid  # warnings do not invalidate
        assert any("unknown frontmatter keys" in w for w in r.warnings)
