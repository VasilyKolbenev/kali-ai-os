"""TDD (red-first) для scripts/release/asset_bootstrap.py — C2 OPUS-103.

Non-destructive premium_assets bootstrap: copy → count/hash verify → switch →
ТОЛЬКО потом удаление legacy junction. Mismatch ⇒ abort без destructive (junction
и его assets целы). Плюс external-writer lockdown: fetch_lgpl_ffmpeg --stage
запрещён (sealed stage пишет только composer).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.release import asset_bootstrap as ab


def _make_junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junctions are Windows-only")
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"mklink /J unavailable: {proc.stderr.strip()}")


def _legacy_layout(tmp_path: Path) -> Path:
    """dist_premium/premium_stage/models (real) + dist_premium/models junction→it."""
    dist = tmp_path / "dist_premium"
    real = dist / "premium_stage" / "models"
    (real / "ffmpeg").mkdir(parents=True)
    (real / "model.bin").write_bytes(b"WEIGHTS")
    (real / "ffmpeg" / "avcodec.dll").write_bytes(b"DLL")
    _make_junction(dist / "models", real)
    return dist


def test_bootstrap_copies_to_sot_and_removes_junction(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    result = ab.bootstrap_premium_assets(dist)
    sot = dist / "premium_assets" / "models"
    assert result == "bootstrapped"
    # physical copy, identical content
    assert (sot / "model.bin").read_bytes() == b"WEIGHTS"
    assert (sot / "ffmpeg" / "avcodec.dll").read_bytes() == b"DLL"
    # integrity manifest written
    assert (dist / "premium_assets" / "PREMIUM_ASSETS.sha256.json").is_file()
    # legacy junction removed (the switch happened)
    assert not (dist / "models").exists()
    # but the real assets it pointed at survive (junction remove ≠ target delete)
    assert (dist / "premium_stage" / "models" / "model.bin").read_bytes() == b"WEIGHTS"


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    result = ab.bootstrap_premium_assets(dist)  # second run
    assert result == "already"
    assert (dist / "premium_assets" / "models" / "model.bin").read_bytes() == b"WEIGHTS"


def test_bootstrap_mismatch_aborts_without_destroying_junction(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)

    def _bad_copier(src: Path, dst: Path) -> None:
        # faithful copy, then drop a file → count/hash verify must FAIL
        import shutil
        shutil.copytree(src, dst)
        (dst / "model.bin").unlink()

    with pytest.raises(ab.BootstrapError):
        ab.bootstrap_premium_assets(dist, copier=_bad_copier)
    # NON-DESTRUCTIVE: legacy junction and its assets remain intact
    assert (dist / "models").exists()
    assert (dist / "premium_stage" / "models" / "model.bin").read_bytes() == b"WEIGHTS"


def test_bootstrap_verifies_sot_reparse_free(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)

    def _link_copier(src: Path, dst: Path) -> None:
        import shutil
        shutil.copytree(src, dst)
        # sneak a reparse point into the SoT → physical-copy-only must reject
        _make_junction(dst / "sneaky", dist / "premium_stage")

    with pytest.raises(ab.BootstrapError):
        ab.bootstrap_premium_assets(dist, copier=_link_copier)
    assert (dist / "models").exists()  # non-destructive on failure


# ── external-writer lockdown: fetch_lgpl_ffmpeg --stage forbidden ───────────
def test_fetch_lgpl_stage_is_forbidden(monkeypatch, tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl

    calls = {"download": 0}

    def _spy_urlretrieve(*a, **k):  # noqa: ANN002, ANN003
        calls["download"] += 1
        return None

    monkeypatch.setattr(fl.urllib.request, "urlretrieve", _spy_urlretrieve)
    monkeypatch.setattr(sys, "argv", ["fetch_lgpl_ffmpeg.py", "--stage"])
    with pytest.raises(SystemExit) as exc:
        fl.main()
    assert exc.value.code != 0                 # fail-closed
    assert calls["download"] == 0              # refused BEFORE any network


def test_fetch_lgpl_without_stage_still_allowed(monkeypatch) -> None:
    # the SoT refresh path (no --stage) must NOT be blocked by the lockdown:
    # parse only, assert --stage default is False (no forbidden exit path).
    import scripts.fetch_lgpl_ffmpeg as fl
    monkeypatch.setattr(sys, "argv", ["fetch_lgpl_ffmpeg.py"])
    # main() would download; we only assert the lockdown does not trip without --stage
    # by checking the guard function directly.
    assert fl.stage_write_forbidden(staged=True) is True
    assert fl.stage_write_forbidden(staged=False) is False
