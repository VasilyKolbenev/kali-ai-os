"""TDD (red-first) для scripts/release/stage_policy.py — C1 OPUS-103.

Модуль ещё не написан → все тесты падают сегодня (ModuleNotFoundError), что и
требуется. Политики чистые: path-safety, reparse-policy, STAGE_MANIFEST schema.

Reparse-точки создаются реальными junction'ами (mklink /J — без admin на
Windows); при невозможности тест skip'ается. Это Windows-build pipeline.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.release import stage_policy as sp


def _make_junction(link: Path, target: Path) -> None:
    """Создать реальный junction link→target (Windows, без admin) или skip."""
    if sys.platform != "win32":
        pytest.skip("junctions are Windows-only")
    target.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"mklink /J unavailable: {proc.stderr.strip()}")


def _dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist_premium"
    d.mkdir()
    return d


# ── reparse detection ───────────────────────────────────────────────────────
def test_is_reparse_point_true_for_junction(tmp_path: Path) -> None:
    link = tmp_path / "j"
    _make_junction(link, tmp_path / "real")
    assert sp.is_reparse_point(link) is True


def test_is_reparse_point_false_for_plain_dir(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sp.is_reparse_point(plain) is False


def test_assert_not_reparse_rejects_junction_root(tmp_path: Path) -> None:
    link = tmp_path / "stage"
    _make_junction(link, tmp_path / "elsewhere")
    with pytest.raises(sp.ReparseError):
        sp.assert_not_reparse(link)


def test_assert_not_reparse_ok_for_plain(tmp_path: Path) -> None:
    plain = tmp_path / "stage"
    plain.mkdir()
    sp.assert_not_reparse(plain)  # не поднимает


# ── sealed-stage: zero reparse points anywhere in tree ──────────────────────
def test_tree_reparse_free_rejects_nested_junction(tmp_path: Path) -> None:
    stage = tmp_path / "sealed"
    (stage / "sub").mkdir(parents=True)
    (stage / "a.txt").write_text("x", encoding="utf-8")
    _make_junction(stage / "sub" / "j", tmp_path / "target")
    with pytest.raises(sp.ReparseError):
        sp.assert_tree_reparse_free(stage)


def test_tree_reparse_free_ok_for_clean_tree(tmp_path: Path) -> None:
    stage = tmp_path / "sealed"
    (stage / "sub").mkdir(parents=True)
    (stage / "sub" / "a.txt").write_text("x", encoding="utf-8")
    sp.assert_tree_reparse_free(stage)  # не поднимает


# ── path safety: dest внутри dist_premium, не root/drive, не == source ───────
def test_assert_safe_dest_within_dist_ok(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    sp.assert_safe_dest(dist, dist / "premium_stage.next-1")  # не поднимает


def test_assert_safe_dest_outside_dist_rejected(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    with pytest.raises(sp.PathSafetyError):
        sp.assert_safe_dest(dist, tmp_path / "outside_stage")


def test_assert_safe_dest_rejects_drive_or_fs_root(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    root = Path(tmp_path.anchor)  # e.g. C:\ or /
    with pytest.raises(sp.PathSafetyError):
        sp.assert_safe_dest(dist, root)


def test_assert_distinct_rejects_source_equals_dest(tmp_path: Path) -> None:
    p = tmp_path / "stage"
    p.mkdir()
    with pytest.raises(sp.PathSafetyError):
        sp.assert_distinct(p, p)


def test_assert_distinct_ok_for_different(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    sp.assert_distinct(a, b)  # не поднимает


# ── HF symlinks в approved source: только внутрь source, не dangling ─────────
def test_source_symlink_escaping_source_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "snap").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "blob").write_bytes(b"X")
    link = source / "snap" / "model.bin"
    try:
        link.symlink_to(outside / "blob")
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(sp.ReparseError):
        sp.assert_source_symlinks_contained(source)


def test_source_symlink_dangling_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "snap").mkdir(parents=True)
    link = source / "snap" / "model.bin"
    try:
        link.symlink_to(source / "blobs" / "missing")
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(sp.ReparseError):
        sp.assert_source_symlinks_contained(source)


def test_source_symlink_contained_ok(tmp_path: Path) -> None:
    source = tmp_path / "source"
    blobs = source / "blobs"
    snap = source / "snap"
    blobs.mkdir(parents=True); snap.mkdir(parents=True)
    (blobs / "b").write_bytes(b"DATA")
    link = snap / "model.bin"
    try:
        link.symlink_to(Path("..") / "blobs" / "b")
    except OSError:
        pytest.skip("symlink creation not permitted")
    sp.assert_source_symlinks_contained(source)  # target внутри source → ok


# ── STAGE_MANIFEST schema ────────────────────────────────────────────────────
def _seed_stage(stage: Path) -> None:
    (stage / "kali-backend").mkdir(parents=True)
    (stage / "kali-backend" / "kali-backend.exe").write_bytes(b"BACKEND")
    (stage / "kali-desktop.exe").write_bytes(b"DESKTOP")


def test_build_manifest_self_excludes_and_hashes_entries(tmp_path: Path) -> None:
    stage = tmp_path / "premium_stage"
    stage.mkdir()
    _seed_stage(stage)
    m = sp.build_manifest(stage, version="1.0.0-rc3", git_sha="abc123",
                          mode="internal", receipts=[{"artifact": "kali-backend"}])
    # поля
    assert m["version"] == "1.0.0-rc3"
    assert m["git_sha"] == "abc123"
    assert m["mode"] == "internal"
    assert m["receipts"] == [{"artifact": "kali-backend"}]
    # entries: relpath → sha256, forward-slash, manifest self-excluded
    assert sp.MANIFEST_NAME not in m["entries"]
    assert "kali-desktop.exe" in m["entries"]
    assert "kali-backend/kali-backend.exe" in m["entries"]
    import hashlib
    assert m["entries"]["kali-desktop.exe"] == hashlib.sha256(b"DESKTOP").hexdigest()


def test_build_manifest_excludes_written_manifest_file(tmp_path: Path) -> None:
    stage = tmp_path / "premium_stage"
    stage.mkdir()
    _seed_stage(stage)
    (stage / sp.MANIFEST_NAME).write_text("{}", encoding="utf-8")  # already present
    m = sp.build_manifest(stage, version="v", git_sha="s", mode="signed", receipts=[])
    assert sp.MANIFEST_NAME not in m["entries"]


def test_verify_manifest_ok_for_exact_stage(tmp_path: Path) -> None:
    stage = tmp_path / "premium_stage"
    stage.mkdir()
    _seed_stage(stage)
    m = sp.build_manifest(stage, version="v", git_sha="s", mode="internal", receipts=[])
    sp.verify_manifest(stage, m)  # не поднимает


@pytest.mark.parametrize("drift", ["extraneous", "mismatch", "missing"])
def test_verify_manifest_detects_drift(tmp_path: Path, drift: str) -> None:
    stage = tmp_path / "premium_stage"
    stage.mkdir()
    _seed_stage(stage)
    m = sp.build_manifest(stage, version="v", git_sha="s", mode="internal", receipts=[])
    if drift == "extraneous":
        (stage / "stray.txt").write_bytes(b"stray")     # файл вне манифеста
    elif drift == "mismatch":
        (stage / "kali-desktop.exe").write_bytes(b"TAMPERED")  # контент изменён
    else:  # missing
        (stage / "kali-desktop.exe").unlink()            # файл из манифеста исчез
    with pytest.raises(sp.ManifestError):
        sp.verify_manifest(stage, m)
