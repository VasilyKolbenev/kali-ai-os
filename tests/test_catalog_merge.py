"""Tests for the community card merge — Supabase UGC ∪ GitHub curated ∪ local.

WS-3 Task 3.5. Drives the PURE merge helper (``kernel/catalog/merge.py``) that
the ``/catalog/community`` route uses to fold the three sources into one deduped,
source-tagged card list:

    * UGC > curated > local on a dedup-key collision (slug if present, else a
      slugified name);
    * order preserved (UGC first, then curated remainder, then local remainder);
    * graceful: every input defaults to ``[]`` (offline Supabase → no UGC, no
      error), and social counts enrich UGC cards when supplied.
"""

from kernel.catalog.merge import (
    SOURCE_CURATED,
    SOURCE_LOCAL,
    SOURCE_UGC,
    merge_community,
    slugify,
)


def test_slugify_normalises_name_and_slug() -> None:
    assert slugify("Weather Bot!") == "weather-bot"
    assert slugify("  PDF__Skill  ") == "pdf-skill"
    assert slugify("") == ""
    assert slugify("---") == ""


def test_merge_tags_sources_and_preserves_order() -> None:
    ugc = [{"slug": "a", "name": "A", "description": "x"}]
    curated = [{"name": "B", "description": "y", "source_id": "kali"}]
    local = [{"name": "C", "description": "z"}]

    cards = merge_community(ugc, curated, local)

    assert [c["name"] for c in cards] == ["A", "B", "C"]
    assert [c["source"] for c in cards] == [SOURCE_UGC, SOURCE_CURATED, SOURCE_LOCAL]


def test_ugc_wins_dedup_over_curated_by_slug_vs_name() -> None:
    # The curated "Shared" collides with the UGC slug "shared" → curated dropped.
    ugc = [{"slug": "shared", "name": "Shared", "description": "live"}]
    curated = [{"name": "Shared", "description": "dup", "source_id": "kali"}]

    cards = merge_community(ugc, curated)

    assert len(cards) == 1
    assert cards[0]["source"] == SOURCE_UGC
    assert cards[0]["description"] == "live"


def test_curated_wins_dedup_over_local() -> None:
    curated = [{"name": "Same", "description": "curated", "source_id": "kali"}]
    local = [{"name": "Same", "description": "local"}]

    cards = merge_community(None, curated, local)

    assert len(cards) == 1
    assert cards[0]["source"] == SOURCE_CURATED


def test_degrades_to_curated_and_local_when_ugc_empty() -> None:
    # Offline Supabase → no UGC. The merge still returns curated ∪ local.
    cards = merge_community(
        [],
        [{"name": "Cur", "description": "c", "source_id": "kali"}],
        [{"name": "Loc", "description": "l"}],
    )
    assert {c["name"] for c in cards} == {"Cur", "Loc"}
    assert all(c["source"] != SOURCE_UGC for c in cards)


def test_social_counts_enrich_ugc_cards() -> None:
    ugc = [{"slug": "wb", "name": "WB", "description": "w"}]
    social = {"wb": {"like_count": 7, "rating_count": 3, "avg_rating": 4.5,
                     "liked": True, "rated": 5}}

    cards = merge_community(ugc, [], social_by_slug=social)

    card = cards[0]
    assert card["like_count"] == 7
    assert card["rating_count"] == 3
    assert card["avg_rating"] == 4.5
    assert card["liked"] is True
    assert card["rated"] == 5


def test_empty_and_unnamed_entries_are_dropped() -> None:
    # A nameless/slug-less row has no dedup key → dropped (not a crash).
    cards = merge_community(
        [{"slug": "", "name": "", "description": "ghost"}],
        [{"name": "Real", "description": "r", "source_id": "kali"}],
    )
    assert [c["name"] for c in cards] == ["Real"]


def test_curated_card_carries_github_install_handle() -> None:
    cards = merge_community(
        None,
        [{"name": "PDF", "description": "p", "source_id": "anthropic",
          "trust": "official", "repo_owner": "anthropics", "metadata": {}}],
    )
    card = cards[0]
    assert card["source_id"] == "anthropic"  # GitHub install keys off this
    assert card["creator_handle"] == "anthropics"
    assert card["slug"] == ""  # curated entries have no Supabase slug
