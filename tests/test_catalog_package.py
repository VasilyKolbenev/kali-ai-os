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
