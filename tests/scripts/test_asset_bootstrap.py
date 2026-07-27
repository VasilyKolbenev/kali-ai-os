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
from scripts.release import stage_policy


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
        ab.refresh_asset_manifest(tmp_path / "dist_premium", owned="ffmpeg")
    assert "SOT_MISSING" in str(exc.value)


# ── H4/D1: пере-запечатывание ТОЛЬКО своего поддерева ───────────────────────
def test_refresh_manifest_refuses_drift_outside_owned_subtree(tmp_path: Path) -> None:
    # дрейф в ассете, которым fetcher НЕ владеет, нельзя отмыть в валидную печать
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    (sot / "model.bin").write_bytes(b"TAMPERED")
    with pytest.raises(ab.BootstrapError) as exc:
        ab.refresh_asset_manifest(dist, owned="ffmpeg")
    assert "SOT_DRIFT" in str(exc.value)
    with pytest.raises(ab.BootstrapError):
        ab.verify_sot_integrity(sot, manifest)  # гейт всё ещё красный


def test_refresh_manifest_reseals_owned_subtree(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    (sot / "ffmpeg" / "avcodec-62.dll").write_bytes(b"NEW-LGPL")  # легальный bump
    ab.refresh_asset_manifest(dist, owned="ffmpeg")
    ab.verify_sot_integrity(sot, manifest)  # снова согласовано


def test_refresh_manifest_refuses_unsealed_sot(tmp_path: Path) -> None:
    # SoT без манифеста нельзя «запечатать» fetcher'ом — печать чеканит только bootstrap
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    _sot, manifest = ab.sot_paths(dist)
    manifest.unlink()
    with pytest.raises(ab.BootstrapError) as exc:
        ab.refresh_asset_manifest(dist, owned="ffmpeg")
    assert "SOT_UNSEALED" in str(exc.value)


def test_ffmpeg_install_does_not_launder_drift(tmp_path: Path) -> None:
    # ровно репро ревью: дрейф F5-чекпойнта + рутинный refresh FFmpeg
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    (sot / "model.bin").write_bytes(b"TAMPERED-MODEL")
    with pytest.raises(ab.BootstrapError) as exc:
        fl.install_into_sot(_fake_lgpl_build(tmp_path), dist)
    assert "SOT_DRIFT" in str(exc.value)
    assert (sot / "model.bin").read_bytes() == b"TAMPERED-MODEL"
    # проверка обязана быть ДО мутации: ни один DLL не должен быть установлен
    assert not (sot / "ffmpeg" / "avcodec-62.dll").exists()
    with pytest.raises(ab.BootstrapError):
        ab.verify_sot_integrity(sot, manifest)  # не отмыто


def _fake_asset_zip(tmp_path: Path) -> tuple[Path, str]:
    """Настоящий zip той же формы, что BtbN-ассет (offline-замена скачивания)."""
    import hashlib
    import zipfile

    import scripts.fetch_lgpl_ffmpeg as fl
    build = "ffmpeg-n8.1-win64-lgpl-shared-8.1"
    zpath = tmp_path / "asset.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(f"{build}/LICENSE.txt", "GNU LESSER GENERAL PUBLIC LICENSE\nversion 2.1")
        for name in fl.EXPECTED_DLLS:
            zf.writestr(f"{build}/bin/{name}", "LGPL")
    return zpath, hashlib.sha256(zpath.read_bytes()).hexdigest()


def _wire_offline_fetch(monkeypatch, tmp_path: Path) -> dict:
    """Подменяет скачивание локальным zip; считает попытки сетевого доступа."""
    import shutil as _shutil

    import scripts.fetch_lgpl_ffmpeg as fl
    zpath, digest = _fake_asset_zip(tmp_path)
    calls = {"download": 0}

    def _spy(url, dst):  # noqa: ANN001
        calls["download"] += 1
        _shutil.copy2(zpath, dst)

    monkeypatch.setattr(fl.urllib.request, "urlretrieve", _spy)
    monkeypatch.setattr(fl, "ASSET_SHA256", digest)
    return calls


def test_ffmpeg_main_end_to_end_offline(monkeypatch, tmp_path: Path) -> None:
    # весь путь main() без сети: SoT-проверка → «скачивание» → SHA → LGPL → install → re-seal
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    calls = _wire_offline_fetch(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["fetch_lgpl_ffmpeg.py", "--dist", str(dist)])
    fl.main()
    assert calls["download"] == 1
    sot, manifest = ab.sot_paths(dist)
    assert (sot / "ffmpeg" / "avcodec-62.dll").read_bytes() == b"LGPL"
    ab.verify_sot_integrity(sot, manifest)


def test_ffmpeg_main_reports_drift_cleanly_not_as_traceback(monkeypatch, tmp_path: Path) -> None:
    # H5: SOT_DRIFT после скачивания обязан быть SystemExit с сообщением, а не голым
    # BootstrapError-traceback (main() не имел обработчика).
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, _manifest = ab.sot_paths(dist)
    (sot / "model.bin").write_bytes(b"TAMPERED")
    _wire_offline_fetch(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["fetch_lgpl_ffmpeg.py", "--dist", str(dist)])
    with pytest.raises(SystemExit) as exc:
        fl.main()
    assert "SOT_DRIFT" in str(exc.value)


def test_ffmpeg_main_requires_seal_before_downloading(monkeypatch, tmp_path: Path) -> None:
    # H5: печать проверяется ДО скачивания — иначе ~70 МБ качаются впустую
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    _sot, manifest = ab.sot_paths(dist)
    manifest.unlink()
    calls = _wire_offline_fetch(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["fetch_lgpl_ffmpeg.py", "--dist", str(dist)])
    with pytest.raises(SystemExit) as exc:
        fl.main()
    assert "SOT_UNSEALED" in str(exc.value)
    assert calls["download"] == 0


def test_ffmpeg_main_requires_sot_before_downloading(monkeypatch, tmp_path: Path) -> None:
    # проверка SoT обязана быть ДО скачивания ~100 МБ
    import scripts.fetch_lgpl_ffmpeg as fl
    calls = {"download": 0}

    def _spy_urlretrieve(*a, **k):  # noqa: ANN002, ANN003
        calls["download"] += 1
        return None

    monkeypatch.setattr(fl.urllib.request, "urlretrieve", _spy_urlretrieve)
    monkeypatch.setattr(sys, "argv",
                        ["fetch_lgpl_ffmpeg.py", "--dist", str(tmp_path / "dist_premium")])
    with pytest.raises(SystemExit) as exc:
        fl.main()
    assert exc.value.code != 0
    assert calls["download"] == 0


def test_verify_sot_integrity_rejects_malformed_manifest(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    manifest.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ab.BootstrapError) as exc:
        ab.verify_sot_integrity(sot, manifest)
    assert "SOT_MANIFEST_MALFORMED" in str(exc.value)


# ── H6-1: immutable asset snapshot (одно чтение манифеста = одна истина) ────
def test_load_asset_snapshot_freezes_bytes_and_entries(tmp_path: Path) -> None:
    import hashlib
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    snap = ab.load_asset_snapshot(manifest)
    assert snap.digest == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert snap.entries == stage_policy.file_content_hashes(sot)


def test_snapshot_digest_is_of_the_bytes_that_were_parsed(tmp_path: Path) -> None:
    # манифест, переписанный ПОСЛЕ снимка, не должен менять ни digest, ни entries
    import hashlib
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    _sot, manifest = ab.sot_paths(dist)
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    snap = ab.load_asset_snapshot(manifest)
    manifest.write_text('{"entries": {"lies.bin": "%s"}}' % ("f" * 64), encoding="utf-8")
    assert snap.digest == before and "lies.bin" not in snap.entries


def test_load_asset_snapshot_reads_the_manifest_exactly_once(tmp_path: Path, monkeypatch) -> None:
    # «один раз» — структурный инвариант: два чтения = окно, в котором файл может
    # измениться между тем, что распарсили, и тем, что захешировали.
    import json as _json
    manifest = tmp_path / "PREMIUM_ASSETS.sha256.json"
    manifest.write_text(_json.dumps({"entries": {"a.bin": "b" * 64}}), encoding="utf-8")
    # считаем только Path.open: Path.read_bytes внутри идёт через него, так что одно
    # логическое чтение = один open, а повторный хеш файла даст второй.
    reads = {"n": 0}
    real_open = Path.open

    def _counting_open(self: Path, *args, **kwargs):  # noqa: ANN202
        if self == manifest:
            reads["n"] += 1
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _counting_open)
    ab.load_asset_snapshot(manifest)
    assert reads["n"] == 1, f"манифест прочитан {reads['n']} раз(а) вместо одного"


@pytest.mark.parametrize("body", ["{ not json", '{"entries": []}', '{"no": "entries"}', "[]"])
def test_load_asset_snapshot_rejects_malformed(tmp_path: Path, body: str) -> None:
    manifest = tmp_path / "PREMIUM_ASSETS.sha256.json"
    manifest.write_text(body, encoding="utf-8")
    with pytest.raises(ab.BootstrapError) as exc:
        ab.load_asset_snapshot(manifest)
    assert "SOT_MANIFEST_MALFORMED" in str(exc.value)


def test_verify_against_snapshot_detects_drift(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    sot, manifest = ab.sot_paths(dist)
    snap = ab.load_asset_snapshot(manifest)
    ab.verify_against_snapshot(sot, snap, what="SoT")  # не поднимает
    (sot / "model.bin").write_bytes(b"DRIFTED")
    with pytest.raises(ab.BootstrapError) as exc:
        ab.verify_against_snapshot(sot, snap, what="SoT")
    assert "SOT_DRIFT" in str(exc.value)


# ── H6-2: точное ТРАНЗАКЦИОННОЕ поддерево ffmpeg + общий asset-lock ─────────
def _seed_stale_subtree(dist: Path) -> Path:
    """Поддерево с мусором, который аддитивное копирование оставляло жить."""
    import scripts.fetch_lgpl_ffmpeg as fl
    target = fl.install_target(dist)
    target.mkdir(parents=True, exist_ok=True)
    (target / "libx264-165.dll").write_bytes(b"GPL")       # запрещённый кодек
    (target / "avcodec-61.dll").write_bytes(b"OLD-SONAME")  # прошлый мажор FFmpeg
    (target / "random.dll").write_bytes(b"JUNK")            # посторонний файл
    return target


def test_ffmpeg_update_removes_stale_x264_and_arbitrary_dlls(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    target = _seed_stale_subtree(dist)  # мусор ВНУТРИ owned-поддерева, ещё не в печати
    fl.install_into_sot(_fake_lgpl_build(tmp_path), dist)
    assert {p.name for p in target.iterdir()} == set(fl.EXPECTED_DLLS) | {"LICENSE.txt"}
    sot, manifest = ab.sot_paths(dist)
    ab.verify_sot_integrity(sot, manifest)


def test_assert_exact_ffmpeg_subtree_rejects_extras_and_gpl(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    tree = tmp_path / "ffmpeg"
    tree.mkdir()
    for name in fl.EXPECTED_DLLS:
        (tree / name).write_bytes(b"LGPL")
    (tree / "LICENSE.txt").write_text("LESSER GENERAL PUBLIC LICENSE", encoding="utf-8")
    fl.assert_exact_ffmpeg_subtree(tree)  # ровно набор → ok
    (tree / "libx265-x.dll").write_bytes(b"GPL")
    with pytest.raises(SystemExit) as exc:
        fl.assert_exact_ffmpeg_subtree(tree)
    assert "GPL" in str(exc.value)
    (tree / "libx265-x.dll").unlink()
    (tree / "extra.dll").write_bytes(b"X")
    with pytest.raises(SystemExit) as exc:
        fl.assert_exact_ffmpeg_subtree(tree)
    assert "INEXACT" in str(exc.value)


def test_ffmpeg_failed_update_preserves_last_good_subtree_and_manifest(
        monkeypatch, tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    target = _seed_stale_subtree(dist)
    _sot, manifest = ab.sot_paths(dist)
    # печать снята ДО появления мусора: если re-seal выполнить раньше успешного свопа,
    # он запечатает несуществующее состояние — и манифест разойдётся с этим снимком.
    before_manifest = manifest.read_bytes()
    before_names = {p.name for p in target.iterdir()}

    calls = {"n": 0}
    real_assert = fl.assert_exact_ffmpeg_subtree

    def _fail_after_promote(tree: Path) -> None:
        calls["n"] += 1
        real_assert(tree)
        if calls["n"] == 2:  # уже после rename в target
            raise SystemExit("injected post-promote failure")

    monkeypatch.setattr(fl, "assert_exact_ffmpeg_subtree", _fail_after_promote)
    with pytest.raises(SystemExit):
        fl.install_into_sot(_fake_lgpl_build(tmp_path), dist)
    assert {p.name for p in target.iterdir()} == before_names  # старое поддерево цело
    assert manifest.read_bytes() == before_manifest            # печать не тронута


# ── H6-2: один asset-lock на fetcher / bootstrap / composer ─────────────────
def test_asset_lock_blocks_a_second_holder(tmp_path: Path) -> None:
    dist = tmp_path / "dist_premium"
    dist.mkdir()
    with ab.asset_lock(dist):
        with pytest.raises(ab.BootstrapError) as exc:
            with ab.asset_lock(dist):
                pass
    assert "ASSETS_LOCKED" in str(exc.value)


def test_bootstrap_refuses_while_assets_locked(tmp_path: Path) -> None:
    dist = _legacy_layout(tmp_path)
    with ab.asset_lock(dist):
        with pytest.raises(ab.BootstrapError) as exc:
            ab.bootstrap_premium_assets(dist)
    assert "ASSETS_LOCKED" in str(exc.value)


def test_fetcher_refuses_while_assets_locked(tmp_path: Path) -> None:
    import scripts.fetch_lgpl_ffmpeg as fl
    dist = _legacy_layout(tmp_path)
    ab.bootstrap_premium_assets(dist)
    with ab.asset_lock(dist):
        with pytest.raises(ab.BootstrapError) as exc:
            fl.install_into_sot(_fake_lgpl_build(tmp_path), dist)
    assert "ASSETS_LOCKED" in str(exc.value)


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
