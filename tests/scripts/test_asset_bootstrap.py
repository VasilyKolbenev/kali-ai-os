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


# ── F1: crash-safe switch completion + physical re-verify + CLI ─────────────
def test_bootstrap_completes_switch_after_crash(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)  # normal: SoT+manifest written, junction removed
    # simulate a crash that left the legacy junction in place after the switch
    _make_junction(dist / "models", dist / "premium_stage" / "models")
    result = ab.bootstrap_premium_assets(dist)  # re-run must safely finish the switch
    assert result == "completed_switch"
    assert not (dist / "models").exists()  # junction removed
    assert (dist / "premium_assets" / "models" / "model.bin").read_bytes() == b"WEIGHTS"


def test_bootstrap_idempotent_rejects_reparse_in_verified_sot(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    _make_junction(dist / "premium_assets" / "models" / "sneaky", dist / "premium_stage")
    with pytest.raises(ab.BootstrapError):
        ab.bootstrap_premium_assets(dist)  # physical-only re-verify catches the reparse


def test_bootstrap_cli_runs(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    rc_code = ab.main([str(dist)])
    assert rc_code == 0
    assert (dist / "premium_assets" / "models" / "model.bin").read_bytes() == b"WEIGHTS"


# ── G5: SoT integrity is load-bearing + fetch is pinned/verified ────────────
def test_verify_sot_integrity_ok_then_drift(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    ab.verify_sot_integrity(sot, manifest)  # matches → ok
    (sot / "model.bin").write_bytes(b"DRIFTED")
    with pytest.raises(ab.BootstrapError) as exc:
        ab.verify_sot_integrity(sot, manifest)
    assert "SOT_DRIFT" in str(exc.value)


def test_ffmpeg_url_is_pinned_not_latest() -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    assert "/latest/" not in fl.ASSET_URL and "-latest-" not in fl.ASSET_URL


def test_ffmpeg_verify_download_refuses_unpinned(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    f = tmp_path / "a.zip"; f.write_bytes(b"x")
    with pytest.raises(SystemExit):
        fl.verify_download_sha256(f, "")  # empty pin → fail-closed


def test_ffmpeg_verify_download_rejects_mismatch(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    f = tmp_path / "a.zip"; f.write_bytes(b"x")
    with pytest.raises(SystemExit):
        fl.verify_download_sha256(f, "00" * 32)


def test_ffmpeg_verify_download_accepts_match(tmp_path: Path) -> None:
    import hashlib
    import scripts.fetch_lgpl_ffmpeg as fl
    f = tmp_path / "a.zip"; f.write_bytes(b"payload")
    fl.verify_download_sha256(f, hashlib.sha256(b"payload").hexdigest())  # matches → ok


# ── H1.1/H1.2: реальный immutable pin + одна правда (premium_assets SoT) ────
def test_ffmpeg_asset_sha256_is_pinned_hex() -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    assert len(fl.ASSET_SHA256) == 64
    assert all(c in "0123456789abcdef" for c in fl.ASSET_SHA256.lower())


def test_ffmpeg_url_pins_an_immutable_dated_tag() -> None:
    import re

    import scripts.fetch_lgpl_ffmpeg as fl
    assert re.search(r"/download/autobuild-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}/", fl.ASSET_URL)
    assert fl.FFMPEG_TAG in fl.ASSET_URL


def test_ffmpeg_install_target_is_the_sot(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = tmp_path / "dist_premium"
    assert fl.install_target(dist) == dist / "premium_assets" / "models" / "ffmpeg"


def _fake_lgpl_build(tmp_path: Path) -> Path:
    import scripts.fetch_lgpl_ffmpeg as fl
    build_dir = tmp_path / "ffmpeg-n8.1-win64-lgpl-shared-8.1"
    (build_dir / "bin").mkdir(parents=True)
    for name in fl.EXPECTED_DLLS:
        (build_dir / "bin" / name).write_bytes(b"LGPL")
    (build_dir / "LICENSE.txt").write_text("LESSER GENERAL PUBLIC LICENSE", encoding="utf-8")
    return build_dir


def test_ffmpeg_install_writes_sot_and_reseals_manifest(tmp_path: Path) -> None:
    # запись в SoT обязана пере-запечатать integrity-манифест, иначе следующий
    # compose упадёт SOT_DRIFT на легальном обновлении FFmpeg.
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    fl.install_into_sot(_fake_lgpl_build(tmp_path), dist)
    sot, manifest = ab.sot_paths(dist)
    assert (sot / "ffmpeg" / "avcodec-62.dll").read_bytes() == b"LGPL"
    ab.verify_sot_integrity(sot, manifest)  # SoT и манифест снова согласованы


def test_ffmpeg_install_fail_closed_without_sot(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    with pytest.raises(SystemExit):
        fl.install_into_sot(_fake_lgpl_build(tmp_path), tmp_path / "dist_premium")


def test_refresh_asset_manifest_requires_sot(tmp_path: Path) -> None:
    with pytest.raises(ab.BootstrapError) as exc:
        ab.refresh_asset_manifest(tmp_path / "dist_premium")
    assert "SOT_MISSING" in str(exc.value)


def test_verify_sot_integrity_rejects_malformed_manifest(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    manifest.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ab.BootstrapError) as exc:
        ab.verify_sot_integrity(sot, manifest)
    assert "SOT_MANIFEST_MALFORMED" in str(exc.value)


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
