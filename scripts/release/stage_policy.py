"""Stage path-safety, reparse policy and STAGE_MANIFEST schema (C1, OPUS-103).

Pure policy for the release stage composer (C5) and the offline smoke (C6):

* **path safety** — a stage/temp/backup destination must live INSIDE
  ``dist_premium`` and never be a drive/filesystem root, a reparse point, or
  identical to its own source (guards a destructive same-path swap).
* **reparse policy** — the root stage/temp/backup and the final *sealed* stage
  must contain zero reparse points; HF symlinks are tolerated ONLY inside an
  approved input source and ONLY when their target stays inside that source
  (no escape, no dangling) — a sealed stage that shipped a ``..\\..\\blobs``
  reparse point breaks offline load on the user's machine.
* **STAGE_MANIFEST** — the immutable pin: ``{relpath: sha256}`` over every file
  except the manifest itself, plus ``version``/``git_sha``/``mode``/``receipts``.

Windows junctions AND POSIX/NT symlinks both count as reparse points. The tree
walks never *descend into* a reparse point (a junction to an ancestor would
otherwise loop).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterator

MANIFEST_NAME = "STAGE_MANIFEST.json"


class StagePolicyError(Exception):
    """Base for every stage-policy violation (fail-closed)."""


class PathSafetyError(StagePolicyError):
    """A stage/temp/backup path is outside dist_premium, a root, or == source."""


class ReparseError(StagePolicyError):
    """A forbidden reparse point (junction/symlink) or an escaping/dangling link."""


class ManifestError(StagePolicyError):
    """The stage content does not match its STAGE_MANIFEST (drift/tamper)."""


# ── reparse detection ───────────────────────────────────────────────────────
def is_reparse_point(path: Path) -> bool:
    """True if ``path`` is a symlink OR a Windows junction (both are reparse)."""
    p = os.fspath(path)
    return os.path.islink(p) or os.path.isjunction(p)


def _scandir_no_follow(root: Path) -> Iterator[Path]:
    """Yield every entry under ``root`` without descending into reparse points."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except NotADirectoryError:
            continue
        for entry in entries:
            child = Path(entry.path)
            yield child
            if is_reparse_point(child):
                continue  # never descend into a reparse point
            if entry.is_dir(follow_symlinks=False):
                stack.append(child)


def assert_not_reparse(path: Path) -> None:
    """Raise if ``path`` itself is a reparse point (root stage/temp/backup)."""
    if is_reparse_point(path):
        raise ReparseError(f"forbidden reparse point at root: {path}")


def assert_tree_reparse_free(root: Path) -> None:
    """Raise if ``root`` or anything under it is a reparse point (sealed stage)."""
    assert_not_reparse(root)
    for child in _scandir_no_follow(root):
        if is_reparse_point(child):
            raise ReparseError(f"forbidden reparse point in sealed stage: {child}")


def assert_source_symlinks_contained(source: Path) -> None:
    """Every reparse under ``source`` must resolve inside ``source``, not dangle."""
    source_resolved = source.resolve()
    for child in _scandir_no_follow(source):
        if not is_reparse_point(child):
            continue
        if not child.exists():  # follows the link → missing target = dangling
            raise ReparseError(f"dangling link in source: {child}")
        target = child.resolve()
        if not target.is_relative_to(source_resolved):
            raise ReparseError(f"link escapes source: {child} -> {target}")


# ── path safety ─────────────────────────────────────────────────────────────
def assert_safe_dest(dist_root: Path, dest: Path) -> None:
    """``dest`` must be inside ``dist_root``, not a root/drive, not a reparse."""
    dest_resolved = dest.resolve()
    if dest_resolved == Path(dest_resolved.anchor):
        raise PathSafetyError(f"refusing a drive/filesystem root as dest: {dest}")
    if not dest_resolved.is_relative_to(dist_root.resolve()):
        raise PathSafetyError(f"dest escapes dist_premium: {dest} !< {dist_root}")
    if dest.exists() and is_reparse_point(dest):
        raise PathSafetyError(f"dest is a reparse point: {dest}")


def assert_distinct(src: Path, dest: Path) -> None:
    """Refuse a swap whose source and destination resolve to the same path."""
    if src.resolve() == dest.resolve():
        raise PathSafetyError(f"source == destination (destructive): {src}")


# ── STAGE_MANIFEST ──────────────────────────────────────────────────────────
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _entry_hashes(stage: Path) -> dict[str, str]:
    """``{relpath: sha256}`` for every regular file except the manifest itself."""
    entries: dict[str, str] = {}
    for child in _scandir_no_follow(stage):
        if is_reparse_point(child) or not child.is_file():
            continue
        rel = child.relative_to(stage).as_posix()
        if rel == MANIFEST_NAME:
            continue
        entries[rel] = _sha256_file(child)
    return entries


def build_manifest(stage: Path, *, version: str, git_sha: str, mode: str,
                   receipts: list[Any]) -> dict[str, Any]:
    """Build the STAGE_MANIFEST dict (the manifest file itself is self-excluded)."""
    return {
        "version": version,
        "git_sha": git_sha,
        "mode": mode,
        "receipts": receipts,
        "entries": _entry_hashes(stage),
    }


def verify_manifest(stage: Path, manifest: dict[str, Any]) -> None:
    """Raise ManifestError if the on-disk stage drifts from ``manifest`` entries."""
    expected: dict[str, str] = manifest["entries"]
    actual = _entry_hashes(stage)
    extraneous = sorted(set(actual) - set(expected))
    if extraneous:
        raise ManifestError(f"extraneous files not in manifest: {extraneous}")
    missing = sorted(set(expected) - set(actual))
    if missing:
        raise ManifestError(f"manifest files missing from stage: {missing}")
    mismatched = sorted(k for k in expected if actual[k] != expected[k])
    if mismatched:
        raise ManifestError(f"content mismatch vs manifest: {mismatched}")
