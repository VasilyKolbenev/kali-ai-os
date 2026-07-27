"""TDD (red-first) для scripts/release/stage_composer.py — C5 OPUS-103.

Rollback-safe transactional swap (same-volume lock + recovery journal, оба crash
points) + full compose (copy → exclusions → materialize → reparse-free → sign/mark
→ STAGE_MANIFEST LAST → exact verify → swap). Никакого multi-GB билда — крошечные
фейковые входы; реальный build = live acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release import receipts as rc
from scripts.release import stage_composer as sc
from scripts.release import stage_policy


# ── helpers ─────────────────────────────────────────────────────────────────
def _dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist_premium"
    d.mkdir()
    return d


def _stage_with(dist: Path, name: str, content: bytes) -> Path:
    stage = dist / "premium_stage"
    stage.mkdir()
    (stage / name).write_bytes(content)
    return stage


def _next_with(dist: Path, token: str, name: str, content: bytes) -> Path:
    nxt = dist / f"premium_stage.next-{token}"
    nxt.mkdir()
    (nxt / name).write_bytes(content)
    return nxt


# ── transactional swap: happy path ──────────────────────────────────────────
def test_swap_promotes_next_to_stage_and_cleans_up(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    _stage_with(dist, "marker.txt", b"OLD")
    _next_with(dist, "1", "marker.txt", b"NEW")
    result = sc.transactional_swap(dist, dist / "premium_stage.next-1", token="1")
    assert result == dist / "premium_stage"
    assert (dist / "premium_stage" / "marker.txt").read_bytes() == b"NEW"
    # no leftovers (the lock FILE persists as an anchor; its OS lock is released)
    assert not (dist / "premium_stage.next-1").exists()
    assert not (dist / "premium_stage.backup-1").exists()
    assert not (dist / "premium_stage.swap-journal.json").exists()


def test_swap_refuses_when_lock_held(tmp_path: Path) -> None:
    # G4: a LIVE OS lock blocks a second flow (a mere leftover file does not).
    dist = _dist(tmp_path)
    _stage_with(dist, "m", b"OLD")
    _next_with(dist, "1", "m", b"NEW")
    with sc.swap_lock(dist):  # hold the OS lock
        with pytest.raises(sc.SwapError) as exc:
            sc.transactional_swap(dist, dist / "premium_stage.next-1", token="1")
        assert "SWAP_LOCKED" in str(exc.value)


def test_two_flows_cannot_run_concurrently(tmp_path: Path) -> None:
    # G4: two concurrent composes cannot proceed under one held lock.
    dist = _dist(tmp_path)
    with sc.swap_lock(dist):
        with pytest.raises(sc.SwapError):
            sc.recover_swap(dist)


# ── failure mid-swap auto-rolls-back to last-good (mutation-a target) ────────
def test_swap_failure_preserves_last_good(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    _stage_with(dist, "marker.txt", b"LASTGOOD")
    missing_next = dist / "premium_stage.next-9"  # does NOT exist → promote fails
    with pytest.raises(Exception):
        sc.transactional_swap(dist, missing_next, token="9")
    # last-good MUST survive (backup was a rename, not a destroy)
    assert (dist / "premium_stage" / "marker.txt").read_bytes() == b"LASTGOOD"
    assert not (dist / "premium_stage.swap-journal.json").exists()  # rolled back


# ── recovery: journal stores only a versioned schema + token; paths DERIVED ──
def _journal(dist: Path, phase: str, token: str = "1") -> Path:
    j = dist / "premium_stage.swap-journal.json"
    j.write_text(json.dumps({"schema": 1, "phase": phase, "token": token}),
                 encoding="utf-8")
    return j


def test_recover_restores_last_good_after_backup_crash(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    # crash right after old->backup, before next->stage (phase still backed_up)
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"OLD")
    nxt = dist / "premium_stage.next-1"; nxt.mkdir()
    (nxt / "marker.txt").write_bytes(b"NEW")
    journal = _journal(dist, "backed_up")
    assert sc.recover_swap(dist) == "restored_backup"
    assert (dist / "premium_stage" / "marker.txt").read_bytes() == b"OLD"  # last-good
    assert not nxt.exists() and not journal.exists()


def test_recover_backed_up_keeps_new_when_already_promoted(tmp_path: Path) -> None:
    # crash after next->stage but before the journal moved to 'promoted'
    dist = _dist(tmp_path)
    stage = dist / "premium_stage"; stage.mkdir()
    (stage / "marker.txt").write_bytes(b"NEW")
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"OLD")
    journal = _journal(dist, "backed_up")
    assert sc.recover_swap(dist) == "kept_new"
    assert (stage / "marker.txt").read_bytes() == b"NEW"  # verified new stage kept
    assert not backup.exists() and not journal.exists()


def test_recover_keeps_new_stage_after_promote_crash(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    stage = dist / "premium_stage"; stage.mkdir()
    (stage / "marker.txt").write_bytes(b"NEW")
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"OLD")
    journal = _journal(dist, "promoted")
    assert sc.recover_swap(dist) == "kept_new"
    assert (stage / "marker.txt").read_bytes() == b"NEW"
    assert not backup.exists() and not journal.exists()


def test_recover_prepare_after_backup_restores_canonical(tmp_path: Path) -> None:
    # crash between old->backup and the journal advancing to backed_up (still prepare)
    dist = _dist(tmp_path)
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"CANON")
    journal = _journal(dist, "prepare")
    assert sc.recover_swap(dist) == "restored_backup"
    assert (dist / "premium_stage" / "marker.txt").read_bytes() == b"CANON"
    assert not journal.exists()


def test_recover_malformed_journal_fail_closed_no_delete(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    stage = dist / "premium_stage"; stage.mkdir()
    (stage / "marker.txt").write_bytes(b"LIVE")
    (dist / "premium_stage.swap-journal.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(sc.SwapError):
        sc.recover_swap(dist)
    assert (stage / "marker.txt").read_bytes() == b"LIVE"  # nothing deleted


def test_recover_unknown_phase_fail_closed_no_delete(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    stage = dist / "premium_stage"; stage.mkdir()
    (stage / "marker.txt").write_bytes(b"LIVE")
    _journal(dist, "WAT")
    with pytest.raises(sc.SwapError):
        sc.recover_swap(dist)
    assert (stage / "marker.txt").read_bytes() == b"LIVE"


def test_recover_malicious_token_refuses_and_preserves_outside(tmp_path: Path) -> None:
    # a journal token that would escape dist_premium must never drive an rmtree
    dist = _dist(tmp_path)
    outside = tmp_path / "precious"; outside.mkdir()
    (outside / "keep.txt").write_bytes(b"KEEP")
    _journal(dist, "promoted", token="..\\..\\precious")
    with pytest.raises(sc.SwapError):
        sc.recover_swap(dist)
    assert (outside / "keep.txt").read_bytes() == b"KEEP"  # sibling untouched


def test_recover_ignores_leftover_lock_file(tmp_path: Path) -> None:
    # G4: a leftover lock FILE with no live holder does not block — the OS lock is
    # free once the crashed process died, so recovery acquires it and proceeds.
    dist = _dist(tmp_path)
    (dist / "premium_stage.swap.lock").write_text("nonce", encoding="utf-8")
    assert sc.recover_swap(dist) == "nothing"


def test_recover_under_new_lock_after_crash(tmp_path: Path) -> None:
    # G4: a crash leaves a journal + a stale lock file; recovery runs under a NEW lock.
    dist = _dist(tmp_path)
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"OLD")
    (dist / "premium_stage.swap.lock").write_text("stale", encoding="utf-8")
    _journal(dist, "backed_up")
    assert sc.recover_swap(dist) == "restored_backup"
    assert (dist / "premium_stage" / "marker.txt").read_bytes() == b"OLD"


def test_recover_nothing_without_journal_or_lock(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    assert sc.recover_swap(dist) == "nothing"


# ── full compose: manifest LAST + exact verify (mutation-b target) ──────────
def _mk_inputs(tmp_path: Path) -> dict:
    inp = tmp_path / "inputs"
    backend = inp / "kali-backend"
    (backend / "_internal").mkdir(parents=True)
    (backend / "kali-backend.exe").write_bytes(b"BACKEND")
    (backend / "_internal" / "lib.zip").write_bytes(b"LIB")
    desktop = inp / "kali-desktop.exe"
    desktop.write_bytes(b"DESKTOP")
    sot = inp / "premium_assets" / "models"
    (sot / "ffmpeg").mkdir(parents=True)
    (sot / "model.bin").write_bytes(b"WEIGHTS")
    (sot / "ggml-base.bin").write_bytes(b"DEADWEIGHT")  # excluded
    webview = inp / "install-webview2.ps1"
    webview.write_bytes(b"PSSCRIPT")
    # H2.1/H2.6: every successful compose ships a REAL SoT integrity manifest — the
    # composer refuses to stage assets it cannot pin.
    assets_manifest = inp / "premium_assets" / "PREMIUM_ASSETS.sha256.json"
    assets_manifest.write_text(
        json.dumps({"entries": stage_policy.file_content_hashes(sot)}), encoding="utf-8")
    return {"backend": backend, "desktop_exe": desktop, "assets": sot,
            "assets_manifest": assets_manifest, "webview2": webview}


def _mk_receipts(tmp_path: Path, inputs: dict, version: str) -> dict:
    rd = tmp_path / "receipts"
    rd.mkdir()
    be = rd / "backend.receipt.json"
    rc.write_receipt(inputs["backend"], be, git_sha="a" * 40, version=version,
                     dirty=False, build_kind="pyinstaller-onedir", toolchain="py3.12")
    dt = rd / "desktop.receipt.json"
    rc.write_receipt(inputs["desktop_exe"], dt, git_sha="a" * 40, version=version,
                     dirty=False, build_kind="tauri-release", toolchain="rust")
    return {"backend": be, "desktop": dt}


def _compose(tmp_path: Path, dist: Path, **over) -> Path:
    inputs = _mk_inputs(tmp_path)
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    kwargs = dict(inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                  git_sha="a" * 40, mode="internal",
                  exclusions=["models/ggml-base.bin"],
                  materializer=lambda p: None, signer=lambda p, m: None, token="1")
    kwargs.update(over)
    return sc.compose_stage(dist, **kwargs)


def test_compose_seals_manifest_last_and_verifies(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    stage = _compose(tmp_path, dist)
    assert stage == dist / "premium_stage"
    # all inputs present, incl. install-webview2.ps1
    assert (stage / "install-webview2.ps1").read_bytes() == b"PSSCRIPT"
    assert (stage / "kali-desktop.exe").read_bytes() == b"DESKTOP"
    assert (stage / "kali-backend" / "kali-backend.exe").read_bytes() == b"BACKEND"
    assert (stage / "models" / "model.bin").read_bytes() == b"WEIGHTS"
    # declarative exclusion applied
    assert not (stage / "models" / "ggml-base.bin").exists()
    # manifest LAST + self-excluded + verifies exactly
    manifest = json.loads((stage / stage_policy.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert stage_policy.MANIFEST_NAME not in manifest["entries"]
    assert manifest["mode"] == "internal" and manifest["version"] == "1.0.0-rc3"
    stage_policy.verify_manifest(stage, manifest)  # exact — не поднимает


def test_compose_rejects_artifact_without_receipt(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    receipts["backend"] = tmp_path / "nonexistent.receipt.json"  # missing receipt
    with pytest.raises(rc.ReceiptError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal",
                         exclusions=[], materializer=lambda p: None,
                         signer=lambda p, m: None, token="1")
    assert "RECEIPT_MISSING" in str(exc.value)


def test_compose_rejects_git_sha_mismatch(tmp_path: Path) -> None:
    # F1: both receipts' git_sha must equal the composer's planned git SHA (and each
    # other, and manifest.git_sha). A receipt from a different commit is refused.
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")  # receipts git_sha = "s"*40
    with pytest.raises(rc.ReceiptError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="d" * 40, mode="internal", exclusions=[],  # planned != "s"*40
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "GIT_SHA_MISMATCH" in str(exc.value)


def test_compose_manifest_git_sha_matches_planned(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    stage = _compose(tmp_path, dist)  # planned git_sha = "s"*40, receipts too
    manifest = json.loads((stage / stage_policy.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["git_sha"] == "a" * 40


def test_compose_receipt_survives_contained_symlink(tmp_path: Path) -> None:
    # G3: a contained HF FILE-symlink in the backend is hashed by CONTENT, so the
    # receipt still matches after copy/materialize dereferences it to a real file.
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    be = inputs["backend"]
    (be / "hf" / "blobs").mkdir(parents=True)
    (be / "hf" / "blobs" / "b").write_bytes(b"MODELDATA")
    (be / "hf" / "snapshots").mkdir(parents=True)
    try:
        (be / "hf" / "snapshots" / "model.bin").symlink_to(Path("..") / "blobs" / "b")
    except OSError:
        pytest.skip("no symlink privilege")
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")  # hashes the symlink by content
    stage = sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                             git_sha="a" * 40, mode="internal", exclusions=[],
                             materializer=lambda p: None, signer=lambda p, m: None, token="1")
    manifest = json.loads((stage / stage_policy.MANIFEST_NAME).read_text(encoding="utf-8"))
    stage_policy.verify_manifest(stage, manifest)
    assert (stage / "kali-backend" / "hf" / "snapshots" / "model.bin").read_bytes() == b"MODELDATA"


def test_compose_rejects_junction_in_source_before_copy(tmp_path: Path) -> None:
    # F2: source-containment runs BEFORE copy — a junction in the assets input is
    # refused (only contained HF file-symlinks are tolerated).
    import subprocess, sys
    if sys.platform != "win32":
        pytest.skip("junctions are Windows-only")
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    proc = subprocess.run(["cmd", "/c", "mklink", "/J",
                           str(inputs["assets"] / "sneaky"), str(tmp_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("mklink /J unavailable")
    # H4: a junction inside the assets SoT is now caught by the physical-copy check
    # that runs first (BootstrapError); one in the backend still raises ReparseError.
    # Either way it is refused BEFORE any copy and nothing is created in dist_premium.
    from scripts.release import asset_bootstrap as ab
    with pytest.raises((stage_policy.ReparseError, ab.BootstrapError)) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal", exclusions=[],
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "sneaky" in str(exc.value)
    _assert_dist_untouched(dist)


# ── H2.1: assets_manifest — обязательный вход compose_stage ─────────────────
def _assert_dist_untouched(dist: Path) -> None:
    """Отказ обязан произойти ДО любых copy/seal/swap — в dist_premium ничего нет."""
    assert not (dist / "premium_stage").exists()
    assert not list(dist.glob("premium_stage.next-*"))
    assert not (dist / "premium_stage.swap-journal.json").exists()


def test_compose_requires_assets_manifest(tmp_path: Path) -> None:
    from scripts.release import asset_bootstrap as ab
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    del inputs["assets_manifest"]  # раньше это молча означало «не проверять SoT»
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    with pytest.raises(ab.BootstrapError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal", exclusions=[],
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "SOT_MANIFEST_REQUIRED" in str(exc.value)
    _assert_dist_untouched(dist)


def test_compose_rejects_missing_assets_manifest_file(tmp_path: Path) -> None:
    from scripts.release import asset_bootstrap as ab
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    inputs["assets_manifest"].unlink()
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    with pytest.raises(ab.BootstrapError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal", exclusions=[],
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "SOT_MISSING" in str(exc.value)
    _assert_dist_untouched(dist)


def test_compose_missing_assets_dir_is_a_clean_sot_missing(tmp_path: Path) -> None:
    # H4: отсутствующий premium_assets (текущее состояние машины) обязан давать
    # SOT_MISSING, а не сырой FileNotFoundError из обхода symlink'ов.
    from scripts.release import asset_bootstrap as ab
    import shutil as _shutil
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    _shutil.rmtree(inputs["assets"])
    with pytest.raises(ab.BootstrapError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal", exclusions=[],
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "SOT_MISSING" in str(exc.value)
    _assert_dist_untouched(dist)


def test_compose_rejects_malformed_assets_manifest(tmp_path: Path) -> None:
    from scripts.release import asset_bootstrap as ab
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    inputs["assets_manifest"].write_text("{ not json", encoding="utf-8")
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    with pytest.raises(ab.BootstrapError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal", exclusions=[],
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "SOT_MANIFEST_MALFORMED" in str(exc.value)
    _assert_dist_untouched(dist)


def test_compose_rejects_asset_drift_before_copy(tmp_path: Path) -> None:
    from scripts.release import asset_bootstrap as ab
    dist = _dist(tmp_path)
    inputs = _mk_inputs(tmp_path)
    (inputs["assets"] / "model.bin").write_bytes(b"DRIFTED")  # после запечатывания SoT
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    with pytest.raises(ab.BootstrapError) as exc:
        sc.compose_stage(dist, inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                         git_sha="a" * 40, mode="internal", exclusions=[],
                         materializer=lambda p: None, signer=lambda p, m: None, token="1")
    assert "SOT_DRIFT" in str(exc.value)
    _assert_dist_untouched(dist)


def test_compose_pins_asset_manifest_digest_in_stage_manifest(tmp_path: Path) -> None:
    import hashlib
    dist = _dist(tmp_path)
    stage = _compose(tmp_path, dist)
    sot_manifest = tmp_path / "inputs" / "premium_assets" / "PREMIUM_ASSETS.sha256.json"
    manifest = json.loads((stage / stage_policy.MANIFEST_NAME).read_text(encoding="utf-8"))
    expected = hashlib.sha256(sot_manifest.read_bytes()).hexdigest()
    assert manifest["asset_manifest_sha256"] == expected
    stage_policy.validate_manifest_schema(manifest)


def test_compose_rejects_reparse_after_materialize(tmp_path: Path) -> None:
    dist = _dist(tmp_path)

    def _bad_materializer(stage: Path) -> None:
        import subprocess, sys
        if sys.platform != "win32":
            pytest.skip("junctions are Windows-only")
        target = stage.parent / "reparse-target"
        target.mkdir(exist_ok=True)
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(stage / "sneaky"),
                               str(target)], capture_output=True, text=True)
        if proc.returncode != 0:
            pytest.skip("mklink /J unavailable")

    with pytest.raises(stage_policy.ReparseError):
        _compose(tmp_path, dist, materializer=_bad_materializer)
