"""Community card merge — Supabase UGC ∪ GitHub curated ∪ local, deduped.

WS-3 Task 3.5. The «Сообщество» tab needs ONE list of cards drawn from three
sources that the §4 ``CatalogClient`` (Supabase) and the GitHub ``SkillsCatalog``
expose separately:

    * **ugc** — Supabase ``approved`` skills (``CatalogClient.browse``): the
      user-generated catalog with social counts + creator attribution.
    * **curated** — the vetted GitHub shelf (``SkillsCatalog`` curated source):
      official/verified entries, no Supabase row.
    * **local** — locally-installed agents (``CatalogClient.local_search``): the
      offline fallback so the tab is never empty/error-walled when Supabase is
      down.

This module is PURE (no I/O, no Supabase, no network): it takes the already-
fetched lists and folds them into one deduped, source-tagged list. Keeping it
side-effect-free makes the merge + dedup trivially unit-testable and keeps the
route in ``kernel/main.py`` thin.

Dedup key: the skill **slug** when present, else a slugified **name** (so a
curated GitHub entry — which carries only ``name`` — dedupes against a Supabase
row that published the same skill). UGC wins a collision (it carries the live
social counts + creator handle); curated wins over local. Order is preserved:
UGC first (freshest community work), then the curated remainder, then any
local-only remainder.

Graceful degradation: every input defaults to ``[]`` — an unconfigured/offline
Supabase yields no UGC (``CatalogClient`` already returns ``[]``), so the merge
degrades to curated ∪ local with NO error. The card shape is uniform across
sources so the UI renders one card component.
"""

from __future__ import annotations

import re
from typing import Any

# Card source tags (single source of truth — the UI keys off these).
SOURCE_UGC = "ugc"
SOURCE_CURATED = "curated"
SOURCE_LOCAL = "local"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Normalise a name/slug into a stable dedup key.

    Lowercases, replaces any run of non-alphanumerics with a single hyphen, and
    strips leading/trailing hyphens. Used so a curated GitHub entry (``name``
    only) and a Supabase row (``slug``) for the same skill collide on one key.

    Args:
        value: The raw slug or display name.

    Returns:
        The normalised key (empty string for an empty/symbol-only input).
    """
    return _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")


def _dedup_key(card: dict[str, Any]) -> str:
    """Dedup key for a card: its slug if present, else its slugified name."""
    slug = (card.get("slug") or "").strip()
    return slugify(slug) if slug else slugify(card.get("name", ""))


def _ugc_card(row: dict[str, Any], social: dict[str, Any] | None) -> dict[str, Any]:
    """Map a Supabase ``skills`` row (+ optional social aggregate) to a card.

    Args:
        row: A mapped ``CatalogClient.browse`` skill dict.
        social: Optional ``get_social`` aggregate for this slug (counts +
            viewer state); ``None`` when not fetched.

    Returns:
        A uniform community card tagged ``source="ugc"``.
    """
    social = social or {}
    return {
        "source": SOURCE_UGC,
        "slug": row.get("slug") or "",
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "category": row.get("category"),
        "version": row.get("version") or "1.0.0",
        "creator_id": row.get("creator_id"),
        "creator_handle": row.get("creator_handle"),
        "install_count": int(row.get("install_count") or 0),
        # Social counts (display-only here; the card refines them via /social).
        "like_count": int(social.get("like_count") or 0),
        "rating_count": int(social.get("rating_count") or 0),
        "avg_rating": social.get("avg_rating") or 0,
        "liked": bool(social.get("liked", False)),
        "rated": social.get("rated"),
        "installed": False,
        # Carry the GitHub-only fields as None so the card shape is uniform.
        "source_id": None,
        "trust": "community",
    }


def _curated_card(entry: dict[str, Any]) -> dict[str, Any]:
    """Map a GitHub ``CatalogEntry`` dict to a uniform community card.

    The curated shelf has no Supabase row, so social counts are absent (the card
    simply renders no like/rate affordance for a curated entry — it has no slug
    to attach social rows to). ``source_id``/``name`` are preserved so the
    existing GitHub install path (``/skills/install``) still works.

    Args:
        entry: A ``CatalogEntry.to_dict()`` from ``SkillsCatalog``.

    Returns:
        A uniform community card tagged ``source="curated"``.
    """
    return {
        "source": SOURCE_CURATED,
        "slug": "",  # curated GitHub entries have no Supabase slug
        "name": entry.get("name") or "",
        "description": entry.get("description") or "",
        "category": (entry.get("metadata") or {}).get("category"),
        "version": entry.get("repo_ref") or "main",
        "creator_id": None,
        "creator_handle": entry.get("repo_owner"),
        "install_count": 0,
        "like_count": 0,
        "rating_count": 0,
        "avg_rating": 0,
        "liked": False,
        "rated": None,
        "installed": False,
        # The GitHub install path keys off (source_id, name).
        "source_id": entry.get("source_id"),
        "trust": entry.get("trust") or "community",
    }


def _local_card(pkg: dict[str, Any]) -> dict[str, Any]:
    """Map a locally-installed package dict to a uniform community card.

    Args:
        pkg: A ``CatalogClient.local_search`` result dict.

    Returns:
        A uniform community card tagged ``source="local"`` (``installed=True``).
    """
    return {
        "source": SOURCE_LOCAL,
        "slug": "",
        "name": pkg.get("name") or "",
        "description": pkg.get("description") or "",
        "category": pkg.get("category"),
        "version": pkg.get("version") or "1.0.0",
        "creator_id": None,
        "creator_handle": None,
        "install_count": int(pkg.get("downloads") or 0),
        "like_count": 0,
        "rating_count": 0,
        "avg_rating": 0,
        "liked": False,
        "rated": None,
        "installed": True,
        "source_id": None,
        "trust": pkg.get("trust_level") or "official",
    }


def merge_community(
    ugc: list[dict[str, Any]] | None,
    curated: list[dict[str, Any]] | None,
    local: list[dict[str, Any]] | None = None,
    *,
    social_by_slug: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fold the three sources into one deduped, source-tagged community list.

    Precedence on a dedup-key collision: UGC > curated > local (the first source
    to claim a key wins; later duplicates are dropped). Order: UGC entries first
    in their given order, then the curated remainder, then the local remainder —
    so the freshest community work leads and the offline fallback only fills gaps.

    Args:
        ugc: Supabase ``approved`` skill dicts (``CatalogClient.browse``), or None.
        curated: GitHub ``CatalogEntry.to_dict()`` dicts, or None.
        local: Locally-installed package dicts (offline fallback), or None.
        social_by_slug: Optional ``slug -> get_social`` map enriching UGC cards
            with live counts; missing slugs default to zero counts.

    Returns:
        The merged community cards (uniform shape, each carrying ``source``).
    """
    social_by_slug = social_by_slug or {}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for row in ugc or []:
        if not isinstance(row, dict):
            continue
        card = _ugc_card(row, social_by_slug.get((row.get("slug") or "").strip()))
        key = _dedup_key(card)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(card)

    for entry in curated or []:
        if not isinstance(entry, dict):
            continue
        card = _curated_card(entry)
        key = _dedup_key(card)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(card)

    for pkg in local or []:
        if not isinstance(pkg, dict):
            continue
        card = _local_card(pkg)
        key = _dedup_key(card)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(card)

    return out
