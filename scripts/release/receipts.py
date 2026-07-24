"""BUILD_RECEIPT provenance for staged artifacts (C3, OPUS-103).

A staged backend/desktop artifact is accepted by the composer (C5) only with a
BUILD_RECEIPT proving where it came from:

    git_sha · version · source dirty=false · artifact sha256 · build kind/toolchain

The receipt is written by the build wrapper *after* a successful build (from a
clean dedicated worktree). At stage time the composer re-hashes the artifact and
refuses it unless the hash matches the receipt (no stale/rebuilt artifact sneaks
in) and the source was clean.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from scripts.release import stage_policy

RECEIPT_NAME = "BUILD_RECEIPT.json"
_REQUIRED = ("git_sha", "version", "dirty", "build_kind", "toolchain", "sha256")


class ReceiptError(Exception):
    """A build receipt is missing, malformed, dirty, or does not match the artifact."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def artifact_sha256(artifact: Path) -> str:
    """Content hash of an artifact: a file's sha256, or a dir's Merkle-style digest."""
    if artifact.is_file():
        return _sha256_file(artifact)
    entries: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(artifact):
        base = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not stage_policy.is_reparse_point(base / d)]
        for fn in filenames:
            fp = base / fn
            if stage_policy.is_reparse_point(fp) or fn == RECEIPT_NAME:
                continue
            entries[fp.relative_to(artifact).as_posix()] = _sha256_file(fp)
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_receipt(artifact: Path, *, git_sha: str, version: str, dirty: bool,
                   build_kind: str, toolchain: str) -> dict[str, Any]:
    """Build a receipt dict for ``artifact`` (hashes its current content)."""
    return {
        "git_sha": git_sha,
        "version": version,
        "dirty": dirty,
        "build_kind": build_kind,
        "toolchain": toolchain,
        "sha256": artifact_sha256(artifact),
    }


def write_receipt(artifact: Path, receipt_path: Path, **fields: Any) -> dict[str, Any]:
    """Create and persist a receipt beside ``artifact`` (build-wrapper helper)."""
    receipt = create_receipt(artifact, **fields)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return receipt


def verify_receipt(artifact: Path, receipt: dict[str, Any], *,
                   expected_version: str | None = None) -> None:
    """Raise ReceiptError unless the receipt is well-formed, clean and current."""
    missing = [k for k in _REQUIRED if k not in receipt]
    if missing:
        raise ReceiptError(f"RECEIPT_SCHEMA: missing fields {missing}")
    if not isinstance(receipt["dirty"], bool):
        raise ReceiptError("RECEIPT_SCHEMA: 'dirty' must be a bool")
    if receipt["dirty"]:
        raise ReceiptError("DIRTY_SOURCE: artifact built from a dirty worktree")
    if artifact_sha256(artifact) != receipt["sha256"]:
        raise ReceiptError("SHA_MISMATCH: artifact content does not match its receipt")
    if expected_version is not None and receipt["version"] != expected_version:
        raise ReceiptError(
            f"VERSION_MISMATCH: receipt {receipt['version']} != expected {expected_version}"
        )


def load_receipt(receipt_path: Path) -> dict[str, Any]:
    try:
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ReceiptError(f"RECEIPT_MALFORMED: {receipt_path}: {e}") from e


def require_receipt(artifact: Path, receipt_path: Path, *,
                    expected_version: str | None = None) -> dict[str, Any]:
    """Stage-acceptance gate: no receipt = no stage. Returns the verified receipt."""
    if not receipt_path.is_file():
        raise ReceiptError(f"RECEIPT_MISSING: no BUILD_RECEIPT for {artifact}")
    receipt = load_receipt(receipt_path)
    verify_receipt(artifact, receipt, expected_version=expected_version)
    return receipt
