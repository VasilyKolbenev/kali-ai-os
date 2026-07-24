"""Transactional stage composer with crash recovery (C5, OPUS-103).

Builds a clean, sealed ``premium_stage`` and swaps it into place rollback-safely.

Compose order (each step is explicit; the manifest is written LAST so it pins the
final content and never hashes itself):

    copy inputs (incl. install-webview2.ps1) -> declarative exclusions ->
    materialize HF links -> assert zero reparse points -> sign inner EXE or mark
    internal -> STAGE_MANIFEST.json (LAST) -> exact verify -> transactional swap.

The swap is NOT a bare rename. It is a rollback-safe transactional swap: a
same-volume lock plus a recovery journal, so the last-good stage is never lost.

    old -> backup   (a rename — never a destroy)   [journal: backed_up]
    next -> stage                                   [journal: promoted]
    rm backup, clear journal/lock

An in-process failure auto-rolls-back to the last-good stage. A process crash
leaves the journal; ``recover_swap`` (run before the next compose) finishes it:
a crash before promotion restores the backup, a crash after promotion keeps the
new verified stage and cleans up.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from scripts.release import receipts as rc
from scripts.release import stage_policy

_JOURNAL = "premium_stage.swap-journal.json"
_LOCK = "premium_stage.swap.lock"


class SwapError(Exception):
    """A transactional stage swap could not proceed safely (fail-closed)."""


# ── journal / lock ──────────────────────────────────────────────────────────
def _journal_path(dist: Path) -> Path:
    return dist / _JOURNAL


def _lock_path(dist: Path) -> Path:
    return dist / _LOCK


def _acquire_lock(lock: Path) -> None:
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError as e:
        raise SwapError(f"SWAP_LOCKED: {lock} exists (another swap in progress?)") from e


def _write_journal(journal: Path, phase: str, nxt: Path, stage: Path, backup: Path) -> None:
    journal.write_text(
        json.dumps({"phase": phase, "next": str(nxt), "stage": str(stage),
                    "backup": str(backup)}),
        encoding="utf-8",
    )


def _clear_swap(journal: Path, lock: Path) -> None:
    for p in (journal, lock):
        if p.exists():
            p.unlink()


# ── transactional swap ──────────────────────────────────────────────────────
def transactional_swap(dist_premium: Path, next_stage: Path, *, token: str) -> Path:
    """Promote ``next_stage`` to premium_stage, preserving the last-good stage."""
    stage = dist_premium / "premium_stage"
    backup = dist_premium / f"premium_stage.backup-{token}"
    journal, lock = _journal_path(dist_premium), _lock_path(dist_premium)
    stage_policy.assert_safe_dest(dist_premium, stage)
    stage_policy.assert_safe_dest(dist_premium, backup)
    stage_policy.assert_distinct(next_stage, stage)

    _acquire_lock(lock)
    try:
        _write_journal(journal, "prepare", next_stage, stage, backup)
        if stage.exists():
            os.rename(stage, backup)  # old -> backup: a RENAME, never a destroy
            _write_journal(journal, "backed_up", next_stage, stage, backup)
        os.rename(next_stage, stage)  # next -> stage
        _write_journal(journal, "promoted", next_stage, stage, backup)
    except Exception:
        _rollback(stage, backup, next_stage)
        _clear_swap(journal, lock)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    _clear_swap(journal, lock)
    return stage


def _rollback(stage: Path, backup: Path, next_stage: Path) -> None:
    """Restore the last-good stage after an in-process swap failure."""
    if not stage.exists() and backup.exists():
        os.rename(backup, stage)  # promotion never happened → bring the old one back
    elif stage.exists() and backup.exists():
        shutil.rmtree(backup)  # promotion happened, a later step failed → keep new
    if next_stage.exists():
        shutil.rmtree(next_stage)


def recover_swap(dist_premium: Path) -> str:
    """Finish an interrupted swap from its journal (run before a new compose)."""
    journal, lock = _journal_path(dist_premium), _lock_path(dist_premium)
    if not journal.exists():
        return "nothing"
    data = json.loads(journal.read_text(encoding="utf-8"))
    stage, backup, nxt = (Path(data["stage"]), Path(data["backup"]), Path(data["next"]))
    if data["phase"] == "promoted":
        if backup.exists():
            shutil.rmtree(backup)
        _clear_swap(journal, lock)
        return "kept_new"
    if data["phase"] == "backed_up":
        if not stage.exists() and backup.exists():
            os.rename(backup, stage)
        if nxt.exists():
            shutil.rmtree(nxt)
        _clear_swap(journal, lock)
        return "restored_backup"
    if nxt.exists():  # prepare — nothing was moved yet
        shutil.rmtree(nxt)
    _clear_swap(journal, lock)
    return "discarded_next"


# ── compose pipeline ────────────────────────────────────────────────────────
Materializer = Callable[[Path], None]
Signer = Callable[[Path, str], None]


def _copy_inputs(nxt: Path, inputs: dict[str, Path]) -> None:
    shutil.copytree(inputs["backend"], nxt / "kali-backend")
    shutil.copy2(inputs["desktop_exe"], nxt / "kali-desktop.exe")
    shutil.copytree(inputs["assets"], nxt / "models")
    shutil.copy2(inputs["webview2"], nxt / "install-webview2.ps1")


def _verify_receipts(nxt: Path, receipts: dict[str, Path], version: str,
                     git_sha: str) -> None:
    """Both artifacts' receipts must pin the composer's planned commit (== each
    other, == manifest.git_sha) — no cross-commit backend/desktop mix ships."""
    be = rc.require_receipt(nxt / "kali-backend", receipts["backend"],
                            expected_version=version, expected_git_sha=git_sha)
    dt = rc.require_receipt(nxt / "kali-desktop.exe", receipts["desktop"],
                            expected_version=version, expected_git_sha=git_sha)
    if be["git_sha"] != dt["git_sha"]:
        raise rc.ReceiptError(
            f"GIT_SHA_MISMATCH: backend {be['git_sha']} != desktop {dt['git_sha']}")


def _apply_exclusions(nxt: Path, exclusions: list[str]) -> None:
    for rel in exclusions:
        target = nxt / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def _seal_manifest(nxt: Path, *, version: str, git_sha: str, mode: str,
                   receipts: dict[str, Path]) -> dict[str, Any]:
    receipt_meta = [{"name": k, **rc.load_receipt(p)} for k, p in receipts.items()]
    manifest = stage_policy.build_manifest(nxt, version=version, git_sha=git_sha,
                                           mode=mode, receipts=receipt_meta)
    (nxt / stage_policy.MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def compose_stage(dist_premium: Path, *, inputs: dict[str, Path],
                  receipts: dict[str, Path], version: str, git_sha: str, mode: str,
                  exclusions: list[str], materializer: Materializer, signer: Signer,
                  token: str) -> Path:
    """Compose a clean sealed stage and swap it into place rollback-safely."""
    recover_swap(dist_premium)  # finish any interrupted prior swap first
    nxt = dist_premium / f"premium_stage.next-{token}"
    stage_policy.assert_safe_dest(dist_premium, nxt)
    if nxt.exists():
        shutil.rmtree(nxt)
    nxt.mkdir(parents=True)

    _copy_inputs(nxt, inputs)
    _verify_receipts(nxt, receipts, version, git_sha)
    _apply_exclusions(nxt, exclusions)
    materializer(nxt)
    stage_policy.assert_tree_reparse_free(nxt)  # zero reparse points after materialize
    signer(nxt, mode)
    manifest = _seal_manifest(nxt, version=version, git_sha=git_sha, mode=mode,
                              receipts=receipts)  # MANIFEST LAST
    stage_policy.verify_manifest(nxt, manifest)  # exact verify before the swap
    return transactional_swap(dist_premium, nxt, token=token)
