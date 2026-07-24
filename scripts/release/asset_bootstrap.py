"""Non-destructive premium_assets bootstrap (C2, OPUS-103).

The heavy voice assets currently live under ``dist_premium/premium_stage/models``
and are reached through a legacy junction ``dist_premium/models``. The clean
immutable stage needs a single canonical source-of-truth:

    dist_premium/premium_assets/models/   (a PHYSICAL copy — never a junction)

This module performs the one-time migration SAFELY:

    copy assets -> count/hash verify -> write integrity manifest -> switch
    (remove the legacy junction) -- and ONLY in that order.

If the verify fails (or the copy sneaks in a reparse point) the migration ABORTS
without deleting the legacy junction: the old assets stay reachable, nothing is
moved destructively, and a re-run is safe (idempotent).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from scripts.release import stage_policy

_MANIFEST_NAME = "PREMIUM_ASSETS.sha256.json"
_DEFAULT_DIST = Path(__file__).resolve().parents[2] / "dist_premium"

Copier = Callable[[Path, Path], None]


class BootstrapError(Exception):
    """A premium_assets bootstrap could not complete safely (fail-closed)."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _dir_hashes(root: Path) -> dict[str, str]:
    """``{relpath: sha256}`` for every file under ``root`` (shared content hashing)."""
    return stage_policy.file_content_hashes(root)


def _default_copier(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)  # symlinks=False → physical copy of content


def _verify_copy(source: Path, sot: Path) -> None:
    """Hash-gate: the SoT must reproduce ``source`` file-for-file, byte-for-byte."""
    src_h = _dir_hashes(source)
    dst_h = _dir_hashes(sot)
    if src_h != dst_h:
        missing = sorted(set(src_h) - set(dst_h))
        extra = sorted(set(dst_h) - set(src_h))
        changed = sorted(k for k in src_h if k in dst_h and src_h[k] != dst_h[k])
        raise BootstrapError(
            f"asset copy verify failed (missing={missing} extra={extra} changed={changed})"
        )


def _assert_physical(sot: Path) -> None:
    """Physical-copy-only: a reparse point in the SoT is a migration error."""
    try:
        stage_policy.assert_tree_reparse_free(sot)
    except stage_policy.ReparseError as e:
        raise BootstrapError(f"SoT is not a physical copy: {e}") from e


def _remove_legacy_junction(legacy: Path) -> None:
    """Remove the legacy junction link only (never its target's content)."""
    if stage_policy.is_reparse_point(legacy):
        os.rmdir(legacy)  # drops the reparse point; the real target survives


def sot_paths(dist_premium: Path) -> tuple[Path, Path]:
    """(SoT models dir, integrity manifest) for a dist_premium."""
    assets = dist_premium / "premium_assets"
    return assets / "models", assets / _MANIFEST_NAME


def verify_sot_integrity(sot: Path, manifest_path: Path) -> None:
    """Fail-closed: the premium_assets SoT must be physical-only and byte-identical
    to its integrity manifest. The composer runs this BEFORE copying the assets, so
    any drift after bootstrap stops the build."""
    if not sot.is_dir() or not manifest_path.is_file():
        raise BootstrapError(f"SOT_MISSING: {sot} / {manifest_path}")
    _assert_physical(sot)
    stored: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _dir_hashes(sot) != stored.get("entries"):
        raise BootstrapError("SOT_DRIFT: premium_assets drifted from its integrity manifest")


def asset_manifest_digest(manifest_path: Path) -> str:
    """A digest of the SoT integrity manifest, pinned into STAGE_MANIFEST provenance."""
    return _sha256_file(manifest_path)


def bootstrap_premium_assets(dist_premium: Path, *, copier: Copier | None = None) -> str:
    """Migrate heavy assets to dist_premium/premium_assets/models, safely.

    Returns ``"already"`` when the SoT already exists and verifies against its
    integrity manifest (idempotent no-op), else ``"bootstrapped"``.

    Raises:
        BootstrapError: on a failed copy verify, a non-physical copy, a missing
            legacy source, or a drifted existing SoT. The legacy junction is left
            intact on every failure path.
    """
    copier = copier or _default_copier
    assets_dir = dist_premium / "premium_assets"
    sot = assets_dir / "models"
    manifest = assets_dir / _MANIFEST_NAME

    legacy = dist_premium / "models"

    if sot.is_dir() and manifest.is_file():
        stored: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
        if _dir_hashes(sot) != stored.get("entries"):
            raise BootstrapError("premium_assets SoT drifted from its integrity manifest")
        _assert_physical(sot)  # re-verify the SoT is a physical-only copy (no reparse)
        # crash-safe: a verified SoT with the legacy junction still present means a
        # prior run died between the manifest write and the switch — finish it now.
        if legacy.exists() and stage_policy.is_reparse_point(legacy):
            _remove_legacy_junction(legacy)
            return "completed_switch"
        return "already"

    if not legacy.exists():
        raise BootstrapError(f"legacy assets junction not found: {legacy}")
    source = legacy.resolve()
    if not source.is_dir():
        raise BootstrapError(f"legacy assets source is not a directory: {source}")

    stage_policy.assert_safe_dest(dist_premium, sot)
    stage_policy.assert_distinct(source, sot)

    if sot.exists():
        shutil.rmtree(sot)
    assets_dir.mkdir(parents=True, exist_ok=True)
    copier(source, sot)

    try:
        _assert_physical(sot)
        _verify_copy(source, sot)  # the hash-gate — must pass BEFORE the switch
    except BootstrapError:
        shutil.rmtree(sot, ignore_errors=True)  # non-destructive: drop partial SoT
        raise  # legacy junction untouched

    manifest.write_text(
        json.dumps({"entries": _dir_hashes(sot)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _remove_legacy_junction(legacy)  # switch: only AFTER a verified copy
    return "bootstrapped"


def main(argv: list[str] | None = None) -> int:
    """CLI (build protocol): bootstrap the premium_assets SoT for a dist_premium dir."""
    args = list(sys.argv[1:] if argv is None else argv)
    dist = Path(args[0]) if args else _DEFAULT_DIST
    result = bootstrap_premium_assets(dist)
    print(f"premium_assets bootstrap: {result} ({dist})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
