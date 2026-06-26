"""Tests for the skill publisher."""

from __future__ import annotations

import tarfile
from pathlib import Path
from textwrap import dedent

import pytest

from kernel.skills.publisher import (
    DEFAULT_CATALOG_REPO,
    PublishResult,
    package_skill,
    publish_skill,
    validate_skill,
)


def _make_skill(
    root: Path,
    name: str,
    *,
    description: str = "A solid test skill with enough description to pass validation. Use when testing things.",
    license_: str | None = "MIT",
    body: str = "# Test\n\nInstructions.\n",
    script_content: str | None = None,
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    fm_lines = [f"name: {name}", f"description: {description}"]
    if license_:
        fm_lines.append(f"license: {license_}")
    (d / "SKILL.md").write_text(
        "---\n" + "\n".join(fm_lines) + "\n---\n\n" + body,
        encoding="utf-8",
    )
    if script_content is not None:
        scripts = d / "scripts"
        scripts.mkdir()
        (scripts / "main.py").write_text(script_content, encoding="utf-8")
    return d


class TestValidateSkill:
    def test_valid_skill(self, tmp_path):
        d = _make_skill(tmp_path, "good-skill")
        manifest, errors, warnings = validate_skill(d)
        assert manifest is not None
        assert errors == []

    def test_missing_dir(self, tmp_path):
        manifest, errors, _ = validate_skill(tmp_path / "nonexistent")
        assert manifest is None
        assert any("not found" in e for e in errors)

    def test_missing_skill_md(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        manifest, errors, _ = validate_skill(d)
        assert manifest is None
        assert any("missing" in e for e in errors)

    def test_invalid_name_reported(self, tmp_path):
        d = tmp_path / "Bad-Name"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: Bad-Name\ndescription: Valid-ish description. Use when needed.\n---\n",
            encoding="utf-8",
        )
        _, errors, _ = validate_skill(d)
        assert errors
        assert any("lowercase" in e for e in errors)

    def test_warns_on_missing_license(self, tmp_path):
        d = _make_skill(tmp_path, "no-license", license_=None)
        _, errors, warnings = validate_skill(d)
        assert not errors
        assert any("license" in w for w in warnings)

    def test_warns_on_short_body(self, tmp_path):
        d = _make_skill(tmp_path, "short-body", body="# X\n")
        _, _, warnings = validate_skill(d)
        assert any("body is very short" in w for w in warnings)


class TestPackageSkill:
    def test_creates_tarball(self, tmp_path):
        d = _make_skill(tmp_path, "pkg-test")
        out = tmp_path / "out"
        bundle = package_skill(d, output_dir=out)

        assert bundle.exists()
        assert bundle.suffix == ".gz"
        assert "pkg-test" in bundle.name

        # Verify contents
        with tarfile.open(bundle, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
        assert "pkg-test/SKILL.md" in names

    def test_includes_scripts(self, tmp_path):
        d = _make_skill(
            tmp_path, "with-scripts",
            script_content="def hello():\n    return 'hi'\n",
        )
        out = tmp_path / "out"
        bundle = package_skill(d, output_dir=out, include_scripts=True)

        with tarfile.open(bundle, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
        assert "with-scripts/scripts/main.py" in names

    def test_excludes_scripts_if_flagged(self, tmp_path):
        d = _make_skill(
            tmp_path, "trimmed",
            script_content="x = 1\n",
        )
        out = tmp_path / "out"
        bundle = package_skill(d, output_dir=out, include_scripts=False)

        with tarfile.open(bundle, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
        assert "trimmed/scripts/main.py" not in names
        # Only SKILL.md should be present
        assert names == ["trimmed/SKILL.md"]


class TestPublishSkill:
    def test_successful_publish(self, tmp_path):
        d = _make_skill(tmp_path, "publishable")
        result = publish_skill(d, output_dir=tmp_path / "out")

        assert result.ok
        assert result.skill_name == "publishable"
        assert result.bundle_path is not None
        assert result.bundle_path.exists()
        assert not result.errors
        assert DEFAULT_CATALOG_REPO in result.catalog_repo_url
        assert result.instructions  # has next steps

    def test_fails_on_invalid_frontmatter(self, tmp_path):
        d = tmp_path / "BadName"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: BadName\ndescription: short\n---\n",
            encoding="utf-8",
        )
        result = publish_skill(d, output_dir=tmp_path / "out")
        assert not result.ok
        assert result.errors
        assert result.bundle_path is None

    def test_fails_on_unsafe_script(self, tmp_path):
        d = _make_skill(
            tmp_path, "unsafe",
            script_content="import subprocess\nsubprocess.run(['rm', '-rf', '/'])\n",
        )
        result = publish_skill(d, output_dir=tmp_path / "out")
        assert not result.ok
        assert result.safety_issues
        assert any("subprocess" in s.lower() or "unsafe" in s.lower() for s in result.safety_issues)
        assert result.bundle_path is None

    def test_skip_safety_allows_unsafe(self, tmp_path):
        d = _make_skill(
            tmp_path, "unsafe-but-force",
            script_content="import subprocess\n",
        )
        result = publish_skill(d, output_dir=tmp_path / "out", skip_safety=True)
        # Passes when explicitly bypassed
        assert result.ok
        assert any("skipped" in w.lower() or "untrusted" in w.lower() for w in result.warnings)

    def test_custom_catalog_repo(self, tmp_path):
        d = _make_skill(tmp_path, "custom-target")
        result = publish_skill(
            d,
            catalog_repo="myorg/my-skills",
            output_dir=tmp_path / "out",
        )
        assert "myorg/my-skills" in result.catalog_repo_url

    def test_no_scripts_gate_still_passes(self, tmp_path):
        d = _make_skill(tmp_path, "scriptless")  # no scripts/
        result = publish_skill(d, output_dir=tmp_path / "out")
        assert result.ok
        assert not result.safety_issues


class TestCli:
    def test_cli_success_exit_code(self, tmp_path, capsys):
        d = _make_skill(tmp_path, "cli-test")
        out = tmp_path / "out"

        from kernel.skills.publisher import run_cli

        code = run_cli([str(d), "--output-dir", str(out)])
        assert code == 0
        captured = capsys.readouterr()
        assert "Packaged 'cli-test'" in captured.out

    def test_cli_failure_exit_code(self, tmp_path, capsys):
        d = tmp_path / "BadName"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: BadName\ndescription: bad\n---\n",
            encoding="utf-8",
        )
        from kernel.skills.publisher import run_cli

        code = run_cli([str(d)])
        assert code != 0
        captured = capsys.readouterr()
        assert "FAILED" in captured.err


def test_package_voice_skill_synthesizes_skill_md(tmp_path: Path) -> None:
    """A voice-built skill (manifest.yaml + skill.yaml, no SKILL.md) packages
    into a bundle that carries a synthesized SKILL.md AND the config files."""
    import tarfile
    import yaml as _yaml

    src = tmp_path / "water-tracker"
    src.mkdir()
    (src / "manifest.yaml").write_text(
        _yaml.dump({"name": "water-tracker", "description": "Track water intake daily",
                    "protocol": "skill", "tools": [{"name": "log"}]})
    )
    (src / "skill.yaml").write_text(_yaml.dump({"template": "tracker", "config": {}}))

    bundle = package_skill(src, output_dir=tmp_path / "out")
    with tarfile.open(bundle, "r:gz") as tar:
        names = set(tar.getnames())
    assert "water-tracker/SKILL.md" in names      # synthesized
    assert "water-tracker/manifest.yaml" in names  # carried (registry + tools)
    assert "water-tracker/skill.yaml" in names     # carried (runnable)
