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
import re
import shutil
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Callable, Iterator

from scripts.release import asset_bootstrap, file_lock, stage_policy
from scripts.release import receipts as rc

_JOURNAL = "premium_stage.swap-journal.json"
_LOCK = "premium_stage.swap.lock"


class SwapError(Exception):
    """A transactional stage swap could not proceed safely (fail-closed)."""


# ── journal / lock (paths DERIVED from a validated dist_premium + token) ─────
_SCHEMA = 1
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _journal_path(dist: Path) -> Path:
    return dist / _JOURNAL


def _lock_path(dist: Path) -> Path:
    return dist / _LOCK


def _derive_paths(dist: Path, token: str) -> tuple[Path, Path, Path]:
    """Derive (stage, backup, next) from the token — NEVER trust stored paths.

    A token that could escape dist_premium (path separators / ``..``) is refused,
    and each derived path is safe-dest validated before any rename/rmtree runs."""
    if not (isinstance(token, str) and _TOKEN_RE.match(token) and ".." not in token):
        raise SwapError(f"UNSAFE_TOKEN: {token!r}")
    stage = dist / "premium_stage"
    backup = dist / f"premium_stage.backup-{token}"
    nxt = dist / f"premium_stage.next-{token}"
    for p in (stage, backup, nxt):
        stage_policy.assert_safe_dest(dist, p)
    return stage, backup, nxt


@contextmanager
def swap_lock(dist: Path) -> Iterator[int]:
    """Hold the OS swap lock across a whole recover -> compose -> seal -> swap flow."""
    try:
        fd = file_lock.acquire(_lock_path(dist))
    except file_lock.LockBusy as e:
        raise SwapError(f"SWAP_LOCKED: {e}") from e
    try:
        yield fd
    finally:
        file_lock.release(fd)


def _write_journal(journal: Path, phase: str, token: str) -> None:
    """Atomic journal write: temp → flush/fsync → os.replace (crash-consistent)."""
    tmp = journal.with_suffix(journal.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema": _SCHEMA, "phase": phase, "token": token}))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, journal)


def _load_journal(journal: Path) -> dict[str, Any]:
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SwapError(f"MALFORMED_JOURNAL: {e}") from e
    if not (isinstance(data, dict) and data.get("schema") == _SCHEMA
            and isinstance(data.get("phase"), str) and "token" in data):
        raise SwapError(f"MALFORMED_JOURNAL: {data!r}")
    return data


def _clear_journal(journal: Path) -> None:
    if journal.exists():
        journal.unlink()  # the OS lock is released by closing its fd, not by deletion


# ── transactional swap ──────────────────────────────────────────────────────
def transactional_swap(dist_premium: Path, next_stage: Path, *, token: str,
                       _held: bool = False) -> Path:
    """Promote ``next_stage`` to premium_stage, preserving the last-good stage.

    ``_held`` means the caller (compose) already holds the OS lock across the flow."""
    stage, backup, nxt = _derive_paths(dist_premium, token)
    if next_stage.resolve() != nxt.resolve():
        raise SwapError(f"NEXT_MISMATCH: {next_stage} != derived {nxt}")
    stage_policy.assert_distinct(nxt, stage)
    journal = _journal_path(dist_premium)

    with (nullcontext() if _held else swap_lock(dist_premium)):
        try:
            _write_journal(journal, "prepare", token)
            if stage.exists():
                os.rename(stage, backup)  # old -> backup: a RENAME, never a destroy
                _write_journal(journal, "backed_up", token)
            os.rename(nxt, stage)  # next -> stage
            _write_journal(journal, "promoted", token)
        except Exception:
            _rollback(stage, backup, nxt)
            _clear_journal(journal)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        _clear_journal(journal)
    return stage


def _rollback(stage: Path, backup: Path, next_stage: Path) -> None:
    """Restore the last-good stage after an in-process swap failure."""
    if not stage.exists() and backup.exists():
        os.rename(backup, stage)  # promotion never happened → bring the old one back
    elif stage.exists() and backup.exists():
        shutil.rmtree(backup)  # promotion happened, a later step failed → keep new
    if next_stage.exists():
        shutil.rmtree(next_stage)


def recover_swap(dist_premium: Path, *, _held: bool = False) -> str:
    """Finish an interrupted swap from its journal, UNDER the OS lock.

    A live lock blocks recovery (SWAP_LOCKED); a leftover lock file from a dead
    process does not. Malformed/unknown journals fail closed without deleting
    anything. Paths are derived from the validated dist_premium + token."""
    journal = _journal_path(dist_premium)
    with (nullcontext() if _held else swap_lock(dist_premium)):
        if not journal.exists():
            return "nothing"
        data = _load_journal(journal)  # malformed → SwapError before any deletion
        stage, backup, nxt = _derive_paths(dist_premium, data["token"])  # unsafe token → SwapError
        phase = data["phase"]
        if phase == "promoted":
            if backup.exists():
                shutil.rmtree(backup)
            _clear_journal(journal)
            return "kept_new"
        if phase == "backed_up":
            if stage.exists():  # next already promoted before the journal advanced
                if backup.exists():
                    shutil.rmtree(backup)
                result = "kept_new"
            elif backup.exists():
                os.rename(backup, stage)
                result = "restored_backup"
            else:
                result = "discarded_next"
            if nxt.exists():
                shutil.rmtree(nxt)
            _clear_journal(journal)
            return result
        if phase == "prepare":
            if not stage.exists() and backup.exists():
                os.rename(backup, stage)  # backup happened before the journal advanced
                result = "restored_backup"
            else:
                result = "discarded_next"
            if nxt.exists():
                shutil.rmtree(nxt)
            _clear_journal(journal)
            return result
        raise SwapError(f"UNKNOWN_PHASE: {phase!r}")  # fail-closed, delete nothing


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
                   receipts: dict[str, Path], asset_digest: str) -> dict[str, Any]:
    receipt_meta = [{"name": k, **rc.load_receipt(p)} for k, p in receipts.items()]
    manifest = stage_policy.build_manifest(nxt, version=version, git_sha=git_sha,
                                           mode=mode, receipts=receipt_meta,
                                           asset_manifest_sha256=asset_digest)
    (nxt / stage_policy.MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def compose_stage(dist_premium: Path, *, inputs: dict[str, Path],
                  receipts: dict[str, Path], version: str, git_sha: str, mode: str,
                  exclusions: list[str], materializer: Materializer, signer: Signer,
                  token: str) -> Path:
    """Compose a clean sealed stage and swap it into place rollback-safely.

    G4: the OS swap lock is held across the WHOLE recover -> compose -> seal -> swap
    flow, so a second concurrent compose cannot interleave on the same next-stage.

    H2.1: ``inputs['assets_manifest']`` is MANDATORY — a stage whose assets cannot be
    pinned to a verified premium_assets SoT is refused before ANY filesystem work."""
    assets_manifest = inputs.get("assets_manifest")
    if assets_manifest is None:
        raise asset_bootstrap.BootstrapError(
            "SOT_MANIFEST_REQUIRED: compose needs inputs['assets_manifest'] "
            "(the premium_assets integrity manifest)")
    with swap_lock(dist_premium):
        recover_swap(dist_premium, _held=True)  # finish any interrupted prior swap first

        # H6-1: read the SoT integrity manifest ONCE and freeze it. The same snapshot
        # gates the source BEFORE the copy and the staged copy AFTER it, and its digest
        # is what the STAGE_MANIFEST pins — a manifest rewritten mid-compose can never
        # become the new truth. G5/H2.1: missing, malformed or drifted stops the build
        # here, before anything is created on disk.
        # H6-2: the composer takes the SAME asset lock as the bootstrap and the FFmpeg
        # fetcher, so nothing can mutate the SoT between the verify and the copy. It is
        # taken INSIDE the swap lock; no other flow takes them in the opposite order.
        with asset_bootstrap.asset_lock(dist_premium):
            snapshot = asset_bootstrap.load_asset_snapshot(assets_manifest)
            asset_bootstrap.verify_against_snapshot(inputs["assets"], snapshot,
                                                    what="premium_assets SoT")
            # F2: source-containment BEFORE anything is created — junction/escaping/
            # dangling reject, only contained HF file-symlinks tolerated.
            for key in ("assets", "backend"):
                stage_policy.assert_source_symlinks_contained(inputs[key])

            nxt = dist_premium / f"premium_stage.next-{token}"
            stage_policy.assert_safe_dest(dist_premium, nxt)
            if nxt.exists():
                shutil.rmtree(nxt)
            nxt.mkdir(parents=True)
            try:
                _copy_inputs(nxt, inputs)
                # H6-1: the STAGED assets must match the SAME frozen snapshot — an asset
                # that changed between the verify and the copy is caught here, before the
                # exclusions touch models/ and long before the swap.
                asset_bootstrap.verify_against_snapshot(nxt / "models", snapshot,
                                                        what="staged models")
                _verify_receipts(nxt, receipts, version, git_sha)
                _apply_exclusions(nxt, exclusions)
                materializer(nxt)
                stage_policy.assert_tree_reparse_free(nxt)  # zero reparse after materialize
                signer(nxt, mode)
                manifest = _seal_manifest(nxt, version=version, git_sha=git_sha, mode=mode,
                                          receipts=receipts,
                                          asset_digest=snapshot.digest)  # MANIFEST LAST
                stage_policy.verify_manifest(nxt, manifest)  # exact verify before the swap
            except BaseException:
                # never leave a multi-GB orphaned next-stage behind; last-good untouched
                shutil.rmtree(nxt, ignore_errors=True)
                raise
            return transactional_swap(dist_premium, nxt, token=token, _held=True)
