"""Tests for kernel.catalog.package — pack / unpack / get_package_info."""

import json
import zipfile
from pathlib import Path

import pytest
import yaml

from kernel.catalog.package import get_package_info, pack, unpack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_dir(base: Path, name: str = "test-agent") -> Path:
    """Create a minimal agent directory with manifest.yaml and a source file."""
    agent_dir = base / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": name,
                "version": "1.0.0",
                "description": "Test agent",
                "capabilities": ["test.hello"],
                "protocol": "native",
            }
        )
    )
    (agent_dir / "main.py").write_text("# agent entrypoint\n")
    sub = agent_dir / "lib"
    sub.mkdir()
    (sub / "util.py").write_text("def helper(): pass\n")
    return agent_dir


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------

class TestPack:
    def test_pack_creates_zip_file(self, tmp_path: Path) -> None:
        """pack() produces a file with .kali-agent extension."""
        agent_dir = _make_agent_dir(tmp_path)
        out = pack(agent_dir, tmp_path / "out.kali-agent")

        assert out.exists()
        assert zipfile.is_zipfile(out)

    def test_pack_contains_expected_files(self, tmp_path: Path) -> None:
        """Pack includes manifest.yaml, source files, and checksums.json."""
        agent_dir = _make_agent_dir(tmp_path)
        out = pack(agent_dir, tmp_path / "out.kali-agent")

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())

        assert "manifest.yaml" in names
        assert "main.py" in names
        assert "lib/util.py" in names
        assert "checksums.json" in names

    def test_pack_checksums_are_sha256(self, tmp_path: Path) -> None:
        """checksums.json contains SHA-256 hex strings for each file."""
        import hashlib

        agent_dir = _make_agent_dir(tmp_path)
        out = pack(agent_dir, tmp_path / "out.kali-agent")

        with zipfile.ZipFile(out) as zf:
            checksums = json.loads(zf.read("checksums.json"))

        for rel, digest in checksums.items():
            expected = hashlib.sha256((agent_dir / rel).read_bytes()).hexdigest()
            assert digest == expected, f"Wrong checksum for {rel}"

    def test_pack_default_output_path(self, tmp_path: Path) -> None:
        """Default output is {name}.kali-agent in cwd."""
        import os

        agent_dir = _make_agent_dir(tmp_path, name="my-agent")
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            out = pack(agent_dir)
        finally:
            os.chdir(original_cwd)

        assert out == tmp_path / "my-agent.kali-agent"
        assert out.exists()

    def test_pack_missing_manifest_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError when manifest.yaml is absent."""
        agent_dir = tmp_path / "no-manifest"
        agent_dir.mkdir()
        (agent_dir / "main.py").write_text("pass")

        with pytest.raises(FileNotFoundError, match="manifest.yaml"):
            pack(agent_dir, tmp_path / "out.kali-agent")

    def test_pack_skips_hidden_files(self, tmp_path: Path) -> None:
        """Hidden files (dot-prefixed) are not included in the package."""
        agent_dir = _make_agent_dir(tmp_path)
        (agent_dir / ".env").write_text("SECRET=1")
        out = pack(agent_dir, tmp_path / "out.kali-agent")

        with zipfile.ZipFile(out) as zf:
            assert ".env" not in zf.namelist()


# ---------------------------------------------------------------------------
# unpack
# ---------------------------------------------------------------------------

class TestUnpack:
    def test_unpack_extracts_files(self, tmp_path: Path) -> None:
        """unpack() places all agent files into target_dir."""
        agent_dir = _make_agent_dir(tmp_path / "src")
        pkg = pack(agent_dir, tmp_path / "out.kali-agent")

        dest = tmp_path / "dest"
        result = unpack(pkg, dest)

        assert result == dest
        assert (dest / "manifest.yaml").exists()
        assert (dest / "main.py").exists()
        assert (dest / "lib" / "util.py").exists()

    def test_unpack_preserves_content(self, tmp_path: Path) -> None:
        """Round-trip: packed then unpacked file content matches original."""
        agent_dir = _make_agent_dir(tmp_path / "src")
        original_main = (agent_dir / "main.py").read_text()

        pkg = pack(agent_dir, tmp_path / "pkg.kali-agent")
        dest = tmp_path / "dest"
        unpack(pkg, dest)

        assert (dest / "main.py").read_text() == original_main

    def test_unpack_returns_target_dir(self, tmp_path: Path) -> None:
        """unpack() returns the target directory path."""
        agent_dir = _make_agent_dir(tmp_path / "src")
        pkg = pack(agent_dir, tmp_path / "pkg.kali-agent")
        dest = tmp_path / "dest"

        result = unpack(pkg, dest)
        assert result == dest

    def test_unpack_missing_checksums_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError when checksums.json is absent from archive."""
        agent_dir = _make_agent_dir(tmp_path / "src")
        pkg = tmp_path / "bad.kali-agent"

        with zipfile.ZipFile(pkg, "w") as zf:
            zf.write(agent_dir / "manifest.yaml", "manifest.yaml")

        with pytest.raises(FileNotFoundError, match="checksums.json"):
            unpack(pkg, tmp_path / "dest")

    def test_unpack_rejects_zip_slip(self, tmp_path: Path) -> None:
        """Malicious zip with path traversal is rejected."""
        import yaml as _yaml

        malicious_zip = tmp_path / "evil.kali-agent"
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("checksums.json", json.dumps({}))
            zf.writestr("manifest.yaml", _yaml.dump({"name": "evil", "version": "1.0.0"}))
            zf.writestr("../../etc/passwd", "hacked")
        with pytest.raises(ValueError, match="[Zz]ip slip"):
            unpack(malicious_zip, tmp_path / "agents")

    def test_unpack_corrupted_file_raises(self, tmp_path: Path) -> None:
        """ValueError when a file's content has been tampered with."""
        agent_dir = _make_agent_dir(tmp_path / "src")
        pkg = pack(agent_dir, tmp_path / "pkg.kali-agent")

        # Rebuild zip with a corrupted main.py
        corrupted = tmp_path / "corrupted.kali-agent"
        with zipfile.ZipFile(pkg, "r") as src_zf, zipfile.ZipFile(corrupted, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            for item in src_zf.infolist():
                if item.filename == "main.py":
                    dst_zf.writestr(item, b"# CORRUPTED CONTENT")
                else:
                    dst_zf.writestr(item, src_zf.read(item.filename))

        with pytest.raises(ValueError, match="Checksum mismatch"):
            unpack(corrupted, tmp_path / "dest")


# ---------------------------------------------------------------------------
# get_package_info
# ---------------------------------------------------------------------------

class TestGetPackageInfo:
    def test_reads_manifest_without_extracting(self, tmp_path: Path) -> None:
        """get_package_info returns manifest dict without writing to disk."""
        agent_dir = _make_agent_dir(tmp_path / "src", name="my-agent")
        pkg = pack(agent_dir, tmp_path / "pkg.kali-agent")

        info = get_package_info(pkg)

        assert info["name"] == "my-agent"
        assert info["version"] == "1.0.0"
        # Nothing extracted
        assert not (tmp_path / "manifest.yaml").exists()

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError when manifest.yaml absent from archive."""
        pkg = tmp_path / "empty.kali-agent"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("README.txt", "no manifest here")

        with pytest.raises(FileNotFoundError, match="manifest.yaml"):
            get_package_info(pkg)

    def test_returns_full_manifest_fields(self, tmp_path: Path) -> None:
        """All manifest fields are returned correctly."""
        agent_dir = _make_agent_dir(tmp_path / "src", name="full-agent")
        pkg = pack(agent_dir, tmp_path / "pkg.kali-agent")

        info = get_package_info(pkg)

        assert info["protocol"] == "native"
        assert "test.hello" in info["capabilities"]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_roundtrip_all_files_preserved(self, tmp_path: Path) -> None:
        """pack → unpack preserves all file contents exactly."""
        agent_dir = _make_agent_dir(tmp_path / "src")
        (agent_dir / "config.yaml").write_text(yaml.dump({"key": "value"}))

        pkg = pack(agent_dir, tmp_path / "pkg.kali-agent")
        dest = tmp_path / "dest"
        unpack(pkg, dest)

        for orig in agent_dir.rglob("*"):
            if orig.is_dir() or orig.name.startswith("."):
                continue
            rel = orig.relative_to(agent_dir)
            restored = dest / rel
            assert restored.exists(), f"Missing: {rel}"
            assert restored.read_bytes() == orig.read_bytes(), f"Content differs: {rel}"


# ---------------------------------------------------------------------------
# Phase B voice-skill packaging — a voice-built skill (manifest.yaml +
# skill.yaml, NO SKILL.md) must pack into a .kali-agent zip with a synthesized,
# spec-valid SKILL.md so the receiver's strict SKILL.md loader accepts it —
# the same synthesis the Phase A .tar.gz P2P bundle uses (publisher).
# ---------------------------------------------------------------------------

def _make_voice_skill(base: Path, name: str = "water-tracker") -> Path:
    """A voice-built skill: manifest.yaml + skill.yaml, NO SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": name,
                "version": "1.0.0",
                "description": "Track water intake daily",
                "protocol": "skill",
                "tools": [
                    {"name": "log", "description": "Log a data point", "parameters": {}}
                ],
                "capabilities": [f"{name}.log"],
                "permissions": [],
            }
        )
    )
    (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))
    return skill_dir


class TestVoiceSkillPack:
    def test_pack_synthesizes_skill_md_for_voice_skill(self, tmp_path: Path) -> None:
        """A voice skill with no SKILL.md gets a synthesized one inside the zip,
        alongside its manifest.yaml + skill.yaml (so it stays runnable)."""
        skill_dir = _make_voice_skill(tmp_path / "src")
        out = pack(skill_dir, tmp_path / "out.kali-agent")

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert "SKILL.md" in names, "synthesized SKILL.md missing from package"
            assert "manifest.yaml" in names
            assert "skill.yaml" in names
            skill_md = zf.read("SKILL.md").decode("utf-8")

        # The synthesized frontmatter name must equal the dir name so the
        # receiver's load_skill(expected_name=dir) validates after extraction.
        assert "name: water-tracker" in skill_md
        # checksums cover the synthesized member too (verified on unpack).
        with zipfile.ZipFile(out) as zf:
            checksums = json.loads(zf.read("checksums.json"))
        assert "SKILL.md" in checksums

    def test_pack_does_not_resynthesize_when_skill_md_present(
        self, tmp_path: Path
    ) -> None:
        """A SKILL.md-backed skill is packed verbatim — no synthesis, the author's
        SKILL.md is preserved byte-for-byte."""
        skill_dir = _make_voice_skill(tmp_path / "src", name="has-md")
        original = (
            "---\n"
            "name: has-md\n"
            "description: Author-written skill with a real description here.\n"
            "compatibility: protocol=skill\n"
            "---\n\n# has-md\n\nReal body.\n"
        )
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text(original, encoding="utf-8")
        on_disk = skill_md_path.read_bytes()  # source of truth (OS newline policy)

        out = pack(skill_dir, tmp_path / "out.kali-agent")
        with zipfile.ZipFile(out) as zf:
            assert zf.read("SKILL.md") == on_disk

    def test_voice_skill_zip_unpacks_and_is_llm_callable(self, tmp_path: Path) -> None:
        """The Phase B keystone (mirrors the Phase A .tar.gz round-trip): a
        voice-built skill packs into a .kali-agent zip, unpacks with the
        synthesized SKILL.md + carried skill.yaml, and once registered its tool
        is offered to the LLM."""
        from kernel.plugin_registry import PluginRegistry

        skill_dir = _make_voice_skill(tmp_path / "src")
        pkg = pack(skill_dir, tmp_path / "out.kali-agent")

        dest = tmp_path / "installed" / "water-tracker"
        unpack(pkg, dest)
        assert (dest / "SKILL.md").is_file()    # synthesized
        assert (dest / "skill.yaml").is_file()  # carried
        assert (dest / "manifest.yaml").is_file()

        agents = tmp_path / "agents"
        agents.mkdir()
        reg = PluginRegistry(agents)
        reg.register_dir(dest)
        tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
        assert "water-tracker__log" in tool_names

    def test_voice_skill_install_package_registers_callable(
        self, tmp_path: Path
    ) -> None:
        """install_package on a voice-skill .kali-agent zip unpacks AND registers
        it into the live registry so it is immediately LLM-callable (the §4
        reconciliation), without needing a SkillExecutor."""
        import asyncio

        from kernel.catalog.installer import install_package
        from kernel.plugin_registry import PluginRegistry

        skill_dir = _make_voice_skill(tmp_path / "src")
        pkg = pack(skill_dir, tmp_path / "out.kali-agent")

        agents = tmp_path / "agents"
        agents.mkdir()
        reg = PluginRegistry(agents)

        result = asyncio.run(
            install_package(pkg, agents_dir=agents, plugin_registry=reg)
        )
        assert result["status"] == "installed", result
        assert result["name"] == "water-tracker"

        tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
        assert "water-tracker__log" in tool_names

    def test_voice_skill_install_zip_slip_still_blocked(self, tmp_path: Path) -> None:
        """Wiring synthesis + registration must NOT weaken zip-slip protection —
        a malicious member path is still rejected on install."""
        import asyncio

        from kernel.catalog.installer import install_package

        malicious = tmp_path / "evil.kali-agent"
        with zipfile.ZipFile(malicious, "w") as zf:
            zf.writestr("checksums.json", json.dumps({}))
            zf.writestr("manifest.yaml", yaml.dump({"name": "evil", "version": "1.0.0"}))
            zf.writestr("../../etc/passwd", "hacked")

        agents = tmp_path / "agents"
        agents.mkdir()
        result = asyncio.run(install_package(malicious, agents_dir=agents))
        assert result["status"] == "error"
        assert "slip" in result["message"].lower()
        assert not (tmp_path / "etc").exists()
