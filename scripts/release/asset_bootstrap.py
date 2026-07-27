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
from typing import Any, Callable, NamedTuple

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


def sot_ffmpeg_dir(dist_premium: Path) -> Path:
    """The ONE shipping source-of-truth for the LGPL FFmpeg DLLs (H1.2).

    Both the fetcher (which installs them) and the backend build (which swaps them
    into av.libs) resolve the directory here, so ``models/ffmpeg`` in the repo can
    no longer drift away from what the stage actually ships."""
    sot, _ = sot_paths(dist_premium)
    return sot / "ffmpeg"


class AssetSnapshot(NamedTuple):
    """An IMMUTABLE view of the SoT integrity manifest.

    ``digest`` is the sha256 of the exact bytes ``entries`` was parsed from, so the
    provenance pin and the content contract can never come from two different reads
    of a file that changed in between."""

    digest: str
    entries: dict[str, str]


def load_asset_snapshot(manifest_path: Path) -> AssetSnapshot:
    """Read the integrity manifest ONCE and freeze it (bytes + parsed entries)."""
    if not manifest_path.is_file():
        raise BootstrapError(f"SOT_MISSING: {manifest_path}")
    try:
        raw = manifest_path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BootstrapError(f"SOT_MANIFEST_MALFORMED: {manifest_path}: {e}") from e
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        raise BootstrapError(f"SOT_MANIFEST_MALFORMED: {manifest_path}: no 'entries' map")
    return AssetSnapshot(digest=hashlib.sha256(raw).hexdigest(), entries=dict(entries))


def verify_against_snapshot(tree: Path, snapshot: AssetSnapshot, *, what: str) -> None:
    """Fail-closed: ``tree`` must be physical-only and match the FROZEN snapshot.

    Used twice per compose — on the SoT before the copy and on the staged copy after
    it — so an asset that changes mid-compose cannot reach the sealed stage."""
    if not tree.is_dir():
        raise BootstrapError(f"SOT_MISSING: {tree}")
    _assert_physical(tree)
    if _dir_hashes(tree) != snapshot.entries:
        raise BootstrapError(f"SOT_DRIFT: {what} does not match the frozen asset snapshot")


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    return {"entries": load_asset_snapshot(manifest_path).entries}


def verify_sot_integrity(sot: Path, manifest_path: Path) -> None:
    """Fail-closed: the premium_assets SoT must be physical-only and byte-identical
    to its integrity manifest (single-shot convenience over :func:`load_asset_snapshot`)."""
    if not sot.is_dir():
        raise BootstrapError(f"SOT_MISSING: {sot} / {manifest_path}")
    verify_against_snapshot(sot, load_asset_snapshot(manifest_path),
                            what="premium_assets SoT")


def _outside(entries: dict[str, str], prefix: str) -> dict[str, str]:
    return {rel: digest for rel, digest in entries.items() if not rel.startswith(prefix)}


def verify_unowned_unchanged(dist_premium: Path, *, owned: str) -> None:
    """Everything OUTSIDE the ``owned`` subtree must still match the sealed manifest.

    A writer authorized for ONE subtree (the FFmpeg fetcher owns ``models/ffmpeg``)
    must not be able to launder drift elsewhere in the SoT into a fresh, valid-looking
    seal — that would silently defeat the SOT_DRIFT gate the composer depends on."""
    sot, manifest_path = sot_paths(dist_premium)
    if not sot.is_dir():
        raise BootstrapError(f"SOT_MISSING: {sot}")
    if not manifest_path.is_file():
        raise BootstrapError(
            f"SOT_UNSEALED: {manifest_path} is missing — only the bootstrap may mint "
            "the first seal; re-run scripts/release/asset_bootstrap.py")
    _assert_physical(sot)
    prefix = owned if owned.endswith("/") else owned + "/"
    stored = _outside(_load_manifest(manifest_path)["entries"], prefix)
    current = _outside(_dir_hashes(sot), prefix)
    if stored != current:
        raise BootstrapError(
            f"SOT_DRIFT: premium_assets drifted outside {prefix} — refusing to re-seal")


def refresh_asset_manifest(dist_premium: Path, *, owned: str) -> Path:
    """Re-seal the SoT integrity manifest after an AUTHORIZED mutation of ``owned``.

    Only the asset fetcher may call this, and only for the subtree it owns; every
    other change is drift and must be caught by :func:`verify_sot_integrity`."""
    verify_unowned_unchanged(dist_premium, owned=owned)
    sot, manifest_path = sot_paths(dist_premium)
    manifest_path.write_text(
        json.dumps({"entries": _dir_hashes(sot)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def asset_manifest_digest(manifest_path: Path) -> str:
    """A digest of the SoT integrity manifest, pinned into STAGE_MANIFEST provenance.

    Prefer :func:`load_asset_snapshot` when the entries are needed too: taking the
    digest in a second read would pin bytes nobody validated."""
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
        stored = _load_manifest(manifest)
        if _dir_hashes(sot) != stored["entries"]:
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
