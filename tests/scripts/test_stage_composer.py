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
    # no leftovers
    assert not (dist / "premium_stage.next-1").exists()
    assert not (dist / "premium_stage.backup-1").exists()
    assert not (dist / "premium_stage.swap-journal.json").exists()
    assert not (dist / "premium_stage.swap.lock").exists()


def test_swap_refuses_when_locked(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    _stage_with(dist, "m", b"OLD")
    _next_with(dist, "1", "m", b"NEW")
    (dist / "premium_stage.swap.lock").write_text("held", encoding="utf-8")
    with pytest.raises(sc.SwapError) as exc:
        sc.transactional_swap(dist, dist / "premium_stage.next-1", token="1")
    assert "SWAP_LOCKED" in str(exc.value)


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


# ── recovery: crash point 1 (backed_up, no handler ran) restores last-good ───
def test_recover_restores_last_good_after_backup_crash(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    # simulate a process crash right after old->backup, before next->stage
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"OLD")
    nxt = dist / "premium_stage.next-1"; nxt.mkdir()
    (nxt / "marker.txt").write_bytes(b"NEW")
    journal = dist / "premium_stage.swap-journal.json"
    journal.write_text(json.dumps({
        "phase": "backed_up",
        "stage": str(dist / "premium_stage"),
        "backup": str(backup),
        "next": str(nxt),
    }), encoding="utf-8")
    result = sc.recover_swap(dist)
    assert result == "restored_backup"
    assert (dist / "premium_stage" / "marker.txt").read_bytes() == b"OLD"  # last-good
    assert not nxt.exists() and not journal.exists()


# ── recovery: crash point 2 (promoted) keeps NEW stage (mutation-c target) ───
def test_recover_keeps_new_stage_after_promote_crash(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    # after next->stage but before cleanup: stage=NEW, backup=OLD, journal=promoted
    stage = dist / "premium_stage"; stage.mkdir()
    (stage / "marker.txt").write_bytes(b"NEW")
    backup = dist / "premium_stage.backup-1"; backup.mkdir()
    (backup / "marker.txt").write_bytes(b"OLD")
    journal = dist / "premium_stage.swap-journal.json"
    journal.write_text(json.dumps({
        "phase": "promoted",
        "stage": str(stage),
        "backup": str(backup),
        "next": str(dist / "premium_stage.next-1"),
    }), encoding="utf-8")
    result = sc.recover_swap(dist)
    assert result == "kept_new"
    assert (stage / "marker.txt").read_bytes() == b"NEW"  # new verified stage survives
    assert not backup.exists() and not journal.exists()


def test_recover_nothing_without_journal(tmp_path: Path) -> None:
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
    return {"backend": backend, "desktop_exe": desktop, "assets": sot, "webview2": webview}


def _mk_receipts(tmp_path: Path, inputs: dict, version: str) -> dict:
    rd = tmp_path / "receipts"
    rd.mkdir()
    be = rd / "backend.receipt.json"
    rc.write_receipt(inputs["backend"], be, git_sha="s" * 40, version=version,
                     dirty=False, build_kind="pyinstaller-onedir", toolchain="py3.12")
    dt = rd / "desktop.receipt.json"
    rc.write_receipt(inputs["desktop_exe"], dt, git_sha="s" * 40, version=version,
                     dirty=False, build_kind="tauri-release", toolchain="rust")
    return {"backend": be, "desktop": dt}


def _compose(tmp_path: Path, dist: Path, **over) -> Path:
    inputs = _mk_inputs(tmp_path)
    receipts = _mk_receipts(tmp_path, inputs, "1.0.0-rc3")
    kwargs = dict(inputs=inputs, receipts=receipts, version="1.0.0-rc3",
                  git_sha="s" * 40, mode="internal",
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
                         git_sha="s" * 40, mode="internal",
                         exclusions=[], materializer=lambda p: None,
                         signer=lambda p, m: None, token="1")
    assert "RECEIPT_MISSING" in str(exc.value)


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
