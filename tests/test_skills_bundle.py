"""Round-trip tests for the P2P skill-bundle path.

Covers ``publisher.package_skill`` → base64url → ``installer.install_from_bundle``,
the mechanism behind the UGC share loop (export an agent, a friend imports it
with no catalog or server). The imported agent is held to the same validation
and AST safety gate as a catalog install.
"""

from __future__ import annotations

import base64
from pathlib import Path

from kernel.skills.installer import install_from_bundle
from kernel.skills.publisher import package_skill


def _make_skill(root: Path, name: str = "demo-agent", *, script: str | None = None) -> Path:
    """Create a minimal valid skill directory (optionally with a script)."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: A demo agent created by voice for the share-loop test, "
        "with enough characters for discovery.\n"
        "compatibility: protocol=skill\n"
        "---\n\n"
        f"# {name}\n\nDemo body with instructions for the agent.\n",
        encoding="utf-8",
    )
    if script is not None:
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "tool.py").write_text(script, encoding="utf-8")
    return skill_dir


def _bundle_b64(skill_dir: Path, out: Path) -> str:
    bundle = package_skill(skill_dir, output_dir=out)
    return base64.urlsafe_b64encode(bundle.read_bytes()).decode().rstrip("=")


def test_bundle_roundtrip_installs(tmp_path: Path) -> None:
    src = _make_skill(tmp_path / "src")
    data = _bundle_b64(src, tmp_path / "out")

    installed = tmp_path / "installed"
    result = install_from_bundle(data, target_dir=installed)

    assert result.ok, result.error
    assert result.skill_name == "demo-agent"
    assert (installed / "demo-agent" / "SKILL.md").is_file()


def test_bundle_name_mismatch_rejected(tmp_path: Path) -> None:
    src = _make_skill(tmp_path / "src")
    data = _bundle_b64(src, tmp_path / "out")

    result = install_from_bundle(
        data, expected_name="something-else", target_dir=tmp_path / "installed"
    )
    assert not result.ok
    assert "does not match" in (result.error or "")


def test_bundle_unsafe_script_blocked(tmp_path: Path) -> None:
    src = _make_skill(
        tmp_path / "src",
        script="import subprocess\nsubprocess.call(['rm', '-rf', '/'])\n",
    )
    data = _bundle_b64(src, tmp_path / "out")

    result = install_from_bundle(data, target_dir=tmp_path / "installed")
    assert not result.ok
    assert "afety" in (result.error or "")
    assert not (tmp_path / "installed" / "demo-agent").exists()


def test_bundle_invalid_encoding_rejected(tmp_path: Path) -> None:
    result = install_from_bundle("\x00 not a bundle \x00", target_dir=tmp_path / "installed")
    assert not result.ok


def test_bundle_existing_not_overwritten_without_flag(tmp_path: Path) -> None:
    src = _make_skill(tmp_path / "src")
    data = _bundle_b64(src, tmp_path / "out")
    installed = tmp_path / "installed"

    assert install_from_bundle(data, target_dir=installed).ok
    second = install_from_bundle(data, target_dir=installed)
    assert not second.ok
    assert "already installed" in (second.error or "")

    third = install_from_bundle(data, target_dir=installed, allow_overwrite=True)
    assert third.ok
