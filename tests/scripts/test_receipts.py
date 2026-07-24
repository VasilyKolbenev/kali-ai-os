"""TDD (red-first) для scripts/release/receipts.py — C3 OPUS-103.

BUILD_RECEIPT: git SHA · version · source dirty=false · artifact sha256 · build
kind/toolchain. Stage не принимает артефакт без receipt / с dirty / со stale
sha. Reason-token в исключении для mutation-provability.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release import receipts as rc


def _artifact_dir(tmp_path: Path) -> Path:
    art = tmp_path / "kali-backend"
    (art / "_internal").mkdir(parents=True)
    (art / "kali-backend.exe").write_bytes(b"BACKEND-EXE")
    (art / "_internal" / "base_library.zip").write_bytes(b"LIB")
    return art


def _good_receipt(art: Path) -> dict:
    return rc.create_receipt(
        art, git_sha="a" * 40, version="1.0.0-rc3", dirty=False,
        build_kind="pyinstaller-onedir", toolchain="python-3.12/pyinstaller-6",
    )


# ── artifact hashing ────────────────────────────────────────────────────────
def test_artifact_sha256_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    h1 = rc.artifact_sha256(art)
    h2 = rc.artifact_sha256(art)
    assert h1 == h2 and len(h1) == 64
    (art / "kali-backend.exe").write_bytes(b"TAMPERED")
    assert rc.artifact_sha256(art) != h1


def test_artifact_sha256_for_single_file(tmp_path: Path) -> None:
    exe = tmp_path / "kali-desktop.exe"
    exe.write_bytes(b"DESKTOP")
    import hashlib
    assert rc.artifact_sha256(exe) == hashlib.sha256(b"DESKTOP").hexdigest()


# ── verify ──────────────────────────────────────────────────────────────────
def test_create_and_verify_roundtrip(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    rc.verify_receipt(art, receipt)  # не поднимает
    assert receipt["sha256"] == rc.artifact_sha256(art)


def test_verify_rejects_dirty_source(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    receipt["dirty"] = True
    with pytest.raises(rc.ReceiptError) as exc:
        rc.verify_receipt(art, receipt)
    assert "DIRTY_SOURCE" in str(exc.value)


def test_verify_rejects_stale_artifact_sha_mismatch(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    (art / "kali-backend.exe").write_bytes(b"REBUILT-DIFFERENT")  # артефакт изменён
    with pytest.raises(rc.ReceiptError) as exc:
        rc.verify_receipt(art, receipt)
    assert "SHA_MISMATCH" in str(exc.value)


@pytest.mark.parametrize("field", ["git_sha", "version", "dirty", "build_kind",
                                   "toolchain", "sha256"])
def test_verify_rejects_missing_required_field(tmp_path: Path, field: str) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    del receipt[field]
    with pytest.raises(rc.ReceiptError) as exc:
        rc.verify_receipt(art, receipt)
    assert "RECEIPT_SCHEMA" in str(exc.value)


def test_verify_rejects_version_mismatch_when_expected(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    with pytest.raises(rc.ReceiptError) as exc:
        rc.verify_receipt(art, receipt, expected_version="9.9.9")
    assert "VERSION_MISMATCH" in str(exc.value)


# ── require_receipt: stage-acceptance gate ──────────────────────────────────
def test_require_receipt_rejects_absent_receipt(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    with pytest.raises(rc.ReceiptError) as exc:
        rc.require_receipt(art, tmp_path / "BUILD_RECEIPT.json")
    assert "RECEIPT_MISSING" in str(exc.value)


def test_require_receipt_ok_for_valid(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    rp = tmp_path / "BUILD_RECEIPT.json"
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    loaded = rc.require_receipt(art, rp, expected_version="1.0.0-rc3")
    assert loaded["git_sha"] == "a" * 40


def test_require_receipt_rejects_stale_via_gate(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    rp = tmp_path / "BUILD_RECEIPT.json"
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    (art / "kali-backend.exe").write_bytes(b"STALE")  # артефакт разошёлся с receipt
    with pytest.raises(rc.ReceiptError) as exc:
        rc.require_receipt(art, rp)
    assert "SHA_MISMATCH" in str(exc.value)
