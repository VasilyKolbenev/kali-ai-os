"""Tests for the HF-cache symlink materialization staging step."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.materialize_hf_symlinks import materialize_symlinks  # noqa: E402


def _make_hf_fixture(tmp_path: Path, blob_name: str = "deadbeef") -> tuple[Path, Path]:
    """Build a minimal HF-cache repo (one blob + one snapshot symlink to it).

    Skips the test if the OS forbids symlink creation (no privilege / dev mode).

    Returns:
        ``(repo_dir, snapshot_link)``.
    """
    repo = tmp_path / "hub" / "models--charactr--vocos-mel-24khz"
    blobs = repo / "blobs"
    blobs.mkdir(parents=True)
    snap = repo / "snapshots" / "rev1"
    snap.mkdir(parents=True)
    (blobs / blob_name).write_bytes(b"MODELDATA")
    link = snap / "pytorch_model.bin"
    try:
        link.symlink_to(Path("..") / ".." / "blobs" / blob_name)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")
    return repo, link


def test_materialize_replaces_link_with_real_file(tmp_path: Path) -> None:
    repo, link = _make_hf_fixture(tmp_path)
    n, reclaimed = materialize_symlinks(tmp_path)
    assert n == 1
    assert not link.is_symlink()
    assert link.read_bytes() == b"MODELDATA"
    assert not (repo / "blobs").exists()  # duplicate blobs pruned
    assert reclaimed == len(b"MODELDATA")


def test_idempotent_second_run_is_noop(tmp_path: Path) -> None:
    _make_hf_fixture(tmp_path)
    materialize_symlinks(tmp_path)
    n, reclaimed = materialize_symlinks(tmp_path)
    assert n == 0
    assert reclaimed == 0


def test_no_symlinks_leaves_tree_unchanged(tmp_path: Path) -> None:
    (tmp_path / "plain.txt").write_text("hello")
    n, reclaimed = materialize_symlinks(tmp_path)
    assert n == 0
    assert reclaimed == 0
    assert (tmp_path / "plain.txt").read_text() == "hello"


def test_dangling_symlink_raises(tmp_path: Path) -> None:
    repo = tmp_path / "models--x--y"
    (repo / "blobs").mkdir(parents=True)
    snap = repo / "snapshots" / "rev"
    snap.mkdir(parents=True)
    link = snap / "model.bin"
    try:
        link.symlink_to(Path("..") / ".." / "blobs" / "missing")
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(FileNotFoundError):
        materialize_symlinks(tmp_path)
