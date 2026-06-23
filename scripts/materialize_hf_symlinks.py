"""Materialize HuggingFace-cache symlinks in a staged build into real files.

The premium stage ships a HF hub cache whose ``snapshots/<rev>/<file>`` entries
are symlinks into ``blobs/<hash>``. Shipping those symlinks is fragile: the
installer either dereferences them (shipping each model twice — the link target
*and* the blob) or preserves a reparse point whose ``..\\..\\blobs`` target
breaks on the user's machine. In the latter case the offline gate
(``kernel/entry.py`` — it only checks the snapshot dir is non-empty) trusts a
cache that then fails to load vocos/Whisper *offline* instead of degrading to
the cloud path.

This replaces every symlink under a root with a real copy of its target and
prunes the now-unreferenced ``blobs/`` dirs — one real file per snapshot entry,
no symlinks, same on-disk size. Idempotent: a tree without symlinks is left
unchanged.

Run as the last staging step before InnoSetup (wired into
``build_installer_premium.bat``)::

    python scripts/materialize_hf_symlinks.py dist_premium/premium_stage
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

DEFAULT_ROOT = Path("dist_premium/premium_stage")


def _repo_root(link: Path) -> Path | None:
    """Return the HF repo dir — the ancestor that owns a sibling ``blobs/``."""
    for parent in link.parents:
        if (parent / "blobs").is_dir():
            return parent
    return None


def materialize_symlinks(root: Path) -> tuple[int, int]:
    """Replace every symlink under ``root`` with a real copy; prune dead blobs.

    Args:
        root: Directory to walk (the staged build).

    Returns:
        ``(n_materialized, bytes_reclaimed)`` — symlinks turned into real files,
        and bytes freed by removing now-unreferenced ``blobs/`` dirs.

    Raises:
        FileNotFoundError: If a symlink is already dangling (its blob is gone).
            A dangling link in the stage is a build error worth failing on.
    """
    links = [p for p in root.rglob("*") if p.is_symlink()]
    repos: set[Path] = set()
    for link in links:
        target = link.resolve()
        if not target.is_file():
            raise FileNotFoundError(f"dangling symlink in stage: {link} -> {target}")
        tmp = link.with_name(link.name + ".materializing.tmp")
        shutil.copy2(target, tmp)  # copy blob content beside the link
        link.unlink()  # drop the reparse point
        tmp.rename(link)  # the real file now lives at the snapshot path
        repo = _repo_root(link)
        if repo is not None:
            repos.add(repo)

    reclaimed = 0
    for repo in repos:
        blobs = repo / "blobs"
        if blobs.is_dir():
            reclaimed += sum(f.stat().st_size for f in blobs.rglob("*") if f.is_file())
            shutil.rmtree(blobs)
    return len(links), reclaimed


def main(argv: list[str]) -> int:
    """Materialize symlinks under the given root (default ``premium_stage``)."""
    root = Path(argv[1]) if len(argv) > 1 else DEFAULT_ROOT
    if not root.is_dir():
        print(f"ERROR: stage root not found: {root}")
        return 1
    n, reclaimed = materialize_symlinks(root)
    print(
        f"Materialized {n} symlink(s) under {root}; "
        f"reclaimed {reclaimed / 1e6:.1f} MB of duplicate blobs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
