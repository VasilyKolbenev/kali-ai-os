"""TDD (red-first) для scripts/release/receipts.py — C3 OPUS-103.

BUILD_RECEIPT: git SHA · version · source dirty=false · artifact sha256 · build
kind/toolchain. Stage не принимает артефакт без receipt / с dirty / со stale
sha. Reason-token в исключении для mutation-provability.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.release import receipts as rc


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init",), ("config", "user.email", "t@t"), ("config", "user.name", "T"),
                 ("config", "commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "seed.txt").write_text("x", encoding="utf-8")
    (repo / ".gitignore").write_text("dist_premium/\n", encoding="utf-8")  # artifacts ignored
    (repo / "dist_premium").mkdir()
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)
    return repo


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


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


# ── F1: expected_git_sha (wrong receipt git_sha was ACCEPTED — now rejected) ─
def test_verify_rejects_wrong_git_sha(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)  # git_sha = "a"*40
    with pytest.raises(rc.ReceiptError) as exc:
        rc.verify_receipt(art, receipt, expected_git_sha="b" * 40)
    assert "GIT_SHA_MISMATCH" in str(exc.value)


def test_verify_accepts_matching_git_sha(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    rc.verify_receipt(art, receipt, expected_git_sha="a" * 40)  # не поднимает


def test_require_receipt_enforces_expected_git_sha(tmp_path: Path) -> None:
    art = _artifact_dir(tmp_path)
    rp = tmp_path / "BUILD_RECEIPT.json"
    rp.write_text(json.dumps(_good_receipt(art)), encoding="utf-8")
    with pytest.raises(rc.ReceiptError) as exc:
        rc.require_receipt(art, rp, expected_git_sha="c" * 40)
    assert "GIT_SHA_MISMATCH" in str(exc.value)


# ── F1: strict schema (formats + non-empty typed fields) ────────────────────
@pytest.mark.parametrize("mutate,token", [
    (lambda r: r.update(sha256="z" * 64), "RECEIPT_SCHEMA"),        # non-hex sha
    (lambda r: r.update(sha256="a" * 63), "RECEIPT_SCHEMA"),        # short sha
    (lambda r: r.update(git_sha="a" * 39), "RECEIPT_SCHEMA"),       # bad git len
    (lambda r: r.update(git_sha="zz"), "RECEIPT_SCHEMA"),           # non-hex git
    (lambda r: r.update(build_kind=""), "RECEIPT_SCHEMA"),          # empty build_kind
    (lambda r: r.update(toolchain="  "), "RECEIPT_SCHEMA"),         # blank toolchain
    (lambda r: r.update(version=""), "RECEIPT_SCHEMA"),             # empty version
])
def test_schema_rejects_malformed_fields(tmp_path: Path, mutate, token: str) -> None:
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    mutate(receipt)
    with pytest.raises(rc.ReceiptError) as exc:
        rc.verify_receipt(art, receipt)
    assert token in str(exc.value)


# ── F1: production writer computes git itself (caller can't fake dirty) ──────
def test_generate_receipt_computes_head_and_clean(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    art = repo / "dist_premium" / "kali-backend.exe"  # gitignored → tree stays clean
    art.write_bytes(b"BE")
    receipt = rc.generate_receipt(art, repo=repo, version="1.0.0-rc3",
                                  build_kind="pyinstaller", toolchain="py3.12")
    assert receipt["git_sha"] == _head(repo)
    assert receipt["dirty"] is False


def test_generate_receipt_detects_dirty(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "seed.txt").write_text("changed", encoding="utf-8")  # dirty tracked file
    art = repo / "dist_premium" / "art.bin"
    art.write_bytes(b"A")
    receipt = rc.generate_receipt(art, repo=repo, version="v1",
                                  build_kind="k", toolchain="t")
    assert receipt["dirty"] is True


def test_write_build_receipt_cli_writes_real_git_sha(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    art = repo / "dist_premium" / "art.bin"
    art.write_bytes(b"A")
    rp = tmp_path / "BUILD_RECEIPT.json"
    rc.main(["write", str(art), str(rp), "1.0.0-rc3", "tauri", "rust", "--repo", str(repo)])
    written = json.loads(rp.read_text(encoding="utf-8"))
    assert written["git_sha"] == _head(repo)
    assert written["dirty"] is False


# ── G2: build-wrapper provenance (HEAD before/after + real toolchain) ────────
def test_capture_head_state_clean_then_dirty(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    sha, clean = rc.capture_head_state(repo)
    assert sha == _head(repo) and clean is True
    (repo / "seed.txt").write_text("changed", encoding="utf-8")
    _, clean2 = rc.capture_head_state(repo)
    assert clean2 is False


def test_collect_toolchain_uses_real_command_output() -> None:
    import sys as _sys
    tc = rc.collect_toolchain([("python", [_sys.executable, "--version"])])
    assert tc.startswith("python=") and "Python" in tc  # real output, not a label


def test_receipt_records_the_asset_manifest_digest(tmp_path: Path) -> None:
    # H7-4: receipt фиксирует, с какой печатью premium_assets собран артефакт
    art = tmp_path / "a.bin"
    art.write_bytes(b"A")
    receipt = rc.create_receipt(art, git_sha="a" * 40, version="v", dirty=False,
                                build_kind="k", toolchain="t",
                                asset_manifest_sha256="c" * 64)
    assert receipt["asset_manifest_sha256"] == "c" * 64
    rc.verify_receipt(art, receipt)


@pytest.mark.parametrize("bad", ["", "zz" * 32, "c" * 63, 12345])
def test_receipt_schema_rejects_a_malformed_asset_digest(tmp_path: Path, bad) -> None:
    art = tmp_path / "a.bin"
    art.write_bytes(b"A")
    receipt = rc.create_receipt(art, git_sha="a" * 40, version="v", dirty=False,
                                build_kind="k", toolchain="t")
    receipt["asset_manifest_sha256"] = bad
    with pytest.raises(rc.ReceiptError):
        rc.verify_receipt(art, receipt)


def test_finalize_refuses_a_build_that_started_dirty(tmp_path: Path) -> None:
    # H6-3: дерево могло стать чистым к концу сборки — receipt всё равно запрещён,
    # артефакт собран из непрокоммиченного состояния.
    repo = _git_repo(tmp_path)
    head = _head(repo)
    art = repo / "dist_premium" / "art.bin"; art.write_bytes(b"A")
    rp = tmp_path / "r.json"
    with pytest.raises(rc.ReceiptError) as exc:
        rc.finalize_build_receipt(art, rp, repo=repo, version="v1", build_kind="k",
                                  toolchain="t", head_before=head, clean_before=False)
    assert "DIRTY_AT_START" in str(exc.value)
    assert not rp.exists()


def test_finalize_refuses_a_build_that_ended_dirty(tmp_path: Path) -> None:
    # F3.1 (live-gate Gate B 2026-07-29): сборка стартовала на чистом дереве, но
    # сама его испачкала (tsc -b переписал tracked tsbuildinfo, tauri — схемы).
    # Receipt с dirty:true бесполезен — его отвергнет verify_receipt. Значит
    # writer обязан отказать ДО записи, а не оставлять мусорный файл.
    repo = _git_repo(tmp_path)
    head = _head(repo)
    art = repo / "dist_premium" / "art.bin"; art.write_bytes(b"A")
    (repo / "seed.txt").write_text("built-and-dirtied", encoding="utf-8")
    rp = tmp_path / "r.json"
    with pytest.raises(rc.ReceiptError) as exc:
        rc.finalize_build_receipt(art, rp, repo=repo, version="v1", build_kind="k",
                                  toolchain="t", head_before=head, clean_before=True)
    assert "DIRTY_AFTER_BUILD" in str(exc.value)
    assert not rp.exists(), "receipt не должен существовать после отказа"


def test_finalize_still_writes_a_receipt_for_a_fully_clean_build(tmp_path: Path) -> None:
    # Companion к предыдущему: чистая сборка обязана остаться зелёной.
    repo = _git_repo(tmp_path)
    head = _head(repo)
    art = repo / "dist_premium" / "art.bin"; art.write_bytes(b"A")
    rp = tmp_path / "r.json"
    receipt = rc.finalize_build_receipt(art, rp, repo=repo, version="v1", build_kind="k",
                                        toolchain="t", head_before=head, clean_before=True)
    assert receipt["dirty"] is False and rp.exists()


def test_require_receipt_rejects_a_legacy_dirty_receipt_on_disk(tmp_path: Path) -> None:
    # F3.3: уже записанные dirty:true receipts продолжают отвергаться гейтом.
    art = _artifact_dir(tmp_path)
    receipt = _good_receipt(art)
    receipt["dirty"] = True
    rp = tmp_path / "BUILD_RECEIPT.json"
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(rc.ReceiptError) as exc:
        rc.require_receipt(art, rp)
    assert "DIRTY_SOURCE" in str(exc.value)


def test_finalize_build_receipt_rejects_head_move(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    head_before = _head(repo)
    art = repo / "dist_premium" / "art.bin"; art.write_bytes(b"A")
    # HEAD moves during the "build"
    (repo / "seed.txt").write_text("y", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-am", "moved"], check=True, capture_output=True)
    with pytest.raises(rc.ReceiptError) as exc:
        rc.finalize_build_receipt(art, tmp_path / "r.json", repo=repo, version="v1",
                                  build_kind="pyinstaller", toolchain="python=x", head_before=head_before, clean_before=True)
    assert "HEAD_MOVED" in str(exc.value)


def test_finalize_build_receipt_writes_current_head(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    head_before = _head(repo)
    art = repo / "dist_premium" / "art.bin"; art.write_bytes(b"A")
    rp = tmp_path / "r.json"
    rc.finalize_build_receipt(art, rp, repo=repo, version="v1", build_kind="pyinstaller",
                              toolchain="python=Python 3.12", head_before=head_before, clean_before=True)
    written = json.loads(rp.read_text(encoding="utf-8"))
    assert written["git_sha"] == head_before and written["dirty"] is False
    assert written["toolchain"] == "python=Python 3.12"


def test_stale_receipt_from_other_commit_rejected(tmp_path: Path) -> None:
    # G2 regression: a receipt built at commit A must be refused when composing at B.
    repo = _git_repo(tmp_path)
    art = repo / "dist_premium" / "art.bin"; art.write_bytes(b"A")
    rp = tmp_path / "r.json"
    head_a = _head(repo)
    rc.finalize_build_receipt(art, rp, repo=repo, version="v1", build_kind="k",
                              toolchain="t", head_before=head_a, clean_before=True)
    (repo / "seed.txt").write_text("b", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-am", "B"], check=True, capture_output=True)
    head_b = _head(repo)
    with pytest.raises(rc.ReceiptError) as exc:
        rc.require_receipt(art, rp, expected_git_sha=head_b)  # composing at B
    assert "GIT_SHA_MISMATCH" in str(exc.value)
