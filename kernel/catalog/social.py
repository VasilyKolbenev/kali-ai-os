"""Community social layer — like / rate / comment (§4 social tables).

WS-3 Task 3.4. Split out of ``kernel/catalog/client.py`` (which would otherwise
exceed the 800-line guard) as a MIXIN that ``CatalogClient`` inherits, so the
methods stay callable as ``catalog_client.like(slug)`` while the file stays lean.

The mixin reuses the host's lazy Supabase client (``self._get_client()``) and the
3.3 identity layer (``self.identity``) — the same graceful-degradation +
sign-in-required contract established for publish/install:

    * **likes** — anonymous, device-scoped (``identity.get_device_id()``), 1 per
      device via ``unique(skill_id, device_or_user_id)``. ``like`` is idempotent
      (a second like is a no-op, not a duplicate / error); ``unlike`` removes.
      No sign-in required.
    * **ratings** — account-gated (``identity.current_account_id()``), 1-5 stars,
      1 per user via ``unique(skill_id, user_id)`` (upsert). Honest
      ``{"status": "sign-in required"}`` when signed out — never a fake success.
    * **comments** — account-gated insert; ``status`` defaults to ``pending``
      (the moderation lifecycle is the 3.7 seam). ``list_comments`` returns only
      ``approved`` rows (RLS-enforced; the client also filters, defense in depth).
    * **get_social** — aggregate like count + average / count of ratings, plus
      whether THIS device liked / THIS account rated.

Graceful degradation: an unconfigured / offline Supabase yields ``[]`` / ``0`` /
``{"status": "unconfigured"}`` and never raises. A slug that resolves to no
``skills`` row degrades the same way (nothing to attach social rows to).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# §4 social table names (single source of truth for the mapping).
_SKILLS_TABLE = "skills"
_LIKES_TABLE = "likes"
_RATINGS_TABLE = "ratings"
_COMMENTS_TABLE = "comments"

_STATUS_APPROVED = "approved"
_STATUS_PENDING = "pending"
_UNCONFIGURED: dict[str, str] = {"status": "unconfigured"}
_SIGN_IN_REQUIRED: dict[str, str] = {"status": "sign-in required"}

# Rating bounds (§4: stars CHECK between 1 and 5).
_MIN_STARS = 1
_MAX_STARS = 5
# Comment body length cap (validate at the boundary; a sane UI/DB guard).
_MAX_COMMENT_LEN = 2000

# Columns selected for a public comment (maps to the §4 comments row).
_COMMENT_COLUMNS = "id, skill_id, user_id, body, status, created_at"


def _avg(values: list[int]) -> float:
    """Mean of ``values`` rounded to 2dp, or 0.0 when empty (no ZeroDivision)."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


class SocialMixin:
    """Like / rate / comment methods mixed into ``CatalogClient``.

    Implemented as a mixin (not a standalone client) so the social surface lives
    on the same ``catalog_client`` instance the FastAPI routes already hold, while
    keeping ``client.py`` under the file-size guard. All methods preserve the
    graceful-degradation contract and the account-gated ones honestly require a
    KALI account sign-in.
    """

    async def _resolve_skill_id(self: Any, slug: str) -> str | None:
        """Resolve a ``skills.slug`` to its UUID id (None when unknown/offline).

        Social rows reference ``skill_id`` (a UUID), but the public API and routes
        speak ``slug``. This is the one extra round-trip the social writes/reads
        share; a missing skill degrades the caller to a graceful empty result.

        Args:
            slug: The skill's stable slug.

        Returns:
            The ``skills.id`` UUID, or None if not found / offline.
        """
        client = self._get_client()
        if client is None:
            return None
        try:
            result = (
                client.table(_SKILLS_TABLE)
                .select("id, slug")
                .eq("slug", slug)
                .maybe_single()
                .execute()
            )
            row = result.data if result is not None else None
            if not row:
                return None
            return row.get("id")
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social._resolve_skill_id failed for %r: %s", slug, exc)
            return None

    # ------------------------------------------------------------------ likes

    async def like(self: Any, slug: str) -> dict[str, Any]:
        """Like a skill as the anonymous local device (idempotent, 1 per device).

        Uses the anon device-id (``identity.get_device_id()``) — NO sign-in
        required. Idempotent: if this device already liked the skill the call is a
        no-op (no duplicate insert, no error) and still reports ``liked=True`` —
        an honest reflection of state, not a fake new like.

        Args:
            slug: The skill's slug.

        Returns:
            ``{"status": "ok", "liked": True}`` (or ``"noop"`` when already liked),
            ``{"status": "error"}`` for an unknown slug, or ``{"status":
            "unconfigured"}`` offline.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        device_id = self.identity.get_device_id()
        try:
            skill_id = await self._resolve_skill_id(slug)
            if skill_id is None:
                return {"status": "error", "reason": "unknown_skill"}

            existing = (
                client.table(_LIKES_TABLE)
                .select("id")
                .eq("skill_id", skill_id)
                .eq("device_or_user_id", device_id)
                .maybe_single()
                .execute()
            )
            if existing is not None and existing.data:
                # Already liked by this device → no-op (unique would reject a dup).
                return {"status": "noop", "liked": True}

            client.table(_LIKES_TABLE).insert(
                {"skill_id": skill_id, "device_or_user_id": device_id}
            ).execute()
            return {"status": "ok", "liked": True}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social.like failed for %r: %s", slug, exc)
            return {"status": "error"}

    async def unlike(self: Any, slug: str) -> dict[str, Any]:
        """Remove this device's like from a skill (no-op if not liked).

        Args:
            slug: The skill's slug.

        Returns:
            ``{"status": "ok", "liked": False}``, ``{"status": "error"}`` for an
            unknown slug, or ``{"status": "unconfigured"}`` offline.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        device_id = self.identity.get_device_id()
        try:
            skill_id = await self._resolve_skill_id(slug)
            if skill_id is None:
                return {"status": "error", "reason": "unknown_skill"}

            (
                client.table(_LIKES_TABLE)
                .delete()
                .eq("skill_id", skill_id)
                .eq("device_or_user_id", device_id)
                .execute()
            )
            return {"status": "ok", "liked": False}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social.unlike failed for %r: %s", slug, exc)
            return {"status": "error"}

    # ---------------------------------------------------------------- ratings

    async def set_rating(self: Any, slug: str, stars: int) -> dict[str, Any]:
        """Set this account's 1-5 star rating for a skill (account-gated upsert).

        Account-gated (``identity.current_account_id()``): honestly returns
        ``{"status": "sign-in required"}`` when signed out — it does NOT silently
        succeed. ``stars`` is validated to 1-5 at the boundary before any write.
        Upserts on the ``unique(skill_id, user_id)`` constraint (1 rating/user).

        Args:
            slug: The skill's slug.
            stars: Rating in 1-5.

        Returns:
            ``{"status": "ok", "stars": N}`` on success, ``{"status":
            "sign-in required"}`` when signed out, ``{"status": "invalid"}`` for
            out-of-range stars, or ``{"status": "unconfigured"}`` / ``{"status":
            "error"}`` otherwise.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        account_id = self.identity.current_account_id()
        if account_id is None:
            return dict(_SIGN_IN_REQUIRED)
        if not isinstance(stars, int) or not (_MIN_STARS <= stars <= _MAX_STARS):
            return {"status": "invalid", "reason": "stars_out_of_range"}
        try:
            skill_id = await self._resolve_skill_id(slug)
            if skill_id is None:
                return {"status": "error", "reason": "unknown_skill"}

            client.table(_RATINGS_TABLE).upsert(
                {"skill_id": skill_id, "user_id": account_id, "stars": stars},
                on_conflict="skill_id,user_id",
            ).execute()
            return {"status": "ok", "stars": stars}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social.set_rating failed for %r: %s", slug, exc)
            return {"status": "error"}

    # --------------------------------------------------------------- comments

    async def post_comment(self: Any, slug: str, body: str) -> dict[str, Any]:
        """Post a comment on a skill (account-gated, defaults to ``pending``).

        Account-gated (``identity.current_account_id()``): honest ``{"status":
        "sign-in required"}`` when signed out. ``body`` is validated at the
        boundary (non-empty after strip, length-capped). The inserted row's
        ``status`` defaults to ``pending`` — the moderation lifecycle (approve /
        flag / remove) is the 3.7 seam.

        Args:
            slug: The skill's slug.
            body: The comment text.

        Returns:
            ``{"status": "pending"}`` on a successful insert (awaiting
            moderation), ``{"status": "sign-in required"}`` when signed out,
            ``{"status": "invalid"}`` for an empty/overlong body, or ``{"status":
            "unconfigured"}`` / ``{"status": "error"}`` otherwise.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        account_id = self.identity.current_account_id()
        if account_id is None:
            return dict(_SIGN_IN_REQUIRED)

        text = (body or "").strip()
        if not text or len(text) > _MAX_COMMENT_LEN:
            return {"status": "invalid", "reason": "body_length"}
        try:
            skill_id = await self._resolve_skill_id(slug)
            if skill_id is None:
                return {"status": "error", "reason": "unknown_skill"}

            client.table(_COMMENTS_TABLE).insert(
                {
                    "skill_id": skill_id,
                    "user_id": account_id,
                    "body": text,
                    "status": _STATUS_PENDING,
                }
            ).execute()
            return {"status": _STATUS_PENDING}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social.post_comment failed for %r: %s", slug, exc)
            return {"status": "error"}

    async def list_comments(self: Any, slug: str) -> list[dict[str, Any]]:
        """List a skill's APPROVED comments, newest first.

        RLS already restricts the public read to ``status='approved'``; the client
        re-asserts the filter (defense in depth) and orders by recency.

        Args:
            slug: The skill's slug.

        Returns:
            Approved comment rows, or ``[]`` for an unknown slug / offline / error.
        """
        client = self._get_client()
        if client is None:
            return []
        try:
            skill_id = await self._resolve_skill_id(slug)
            if skill_id is None:
                return []

            result = (
                client.table(_COMMENTS_TABLE)
                .select(_COMMENT_COLUMNS)
                .eq("skill_id", skill_id)
                .eq("status", _STATUS_APPROVED)
                .order("created_at", desc=True)
                .execute()
            )
            rows = result.data if result is not None else None
            return [r for r in (rows or []) if isinstance(r, dict)]
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social.list_comments failed for %r: %s", slug, exc)
            return []

    # ----------------------------------------------------------- aggregate

    async def get_social(self: Any, slug: str) -> dict[str, Any]:
        """Aggregate a skill's social signals (like / rating counts + viewer state).

        Reads the raw ``likes`` and ``ratings`` rows (public-readable per RLS) and
        aggregates them client-side: like count, rating count + average, plus
        whether THIS device liked the skill and what THIS account rated it (None
        when signed out / not yet rated).

        Args:
            slug: The skill's slug.

        Returns:
            ``{"like_count", "rating_count", "avg_rating", "liked", "rated"}``.
            Offline yields the same shape with zeros + a ``"status":
            "unconfigured"`` marker; an unknown slug yields zeros.
        """
        client = self._get_client()
        if client is None:
            return {
                "status": "unconfigured",
                "like_count": 0,
                "rating_count": 0,
                "avg_rating": 0,
                "liked": False,
                "rated": None,
            }

        device_id = self.identity.get_device_id()
        account_id = self.identity.current_account_id()
        zero = {
            "like_count": 0,
            "rating_count": 0,
            "avg_rating": 0,
            "liked": False,
            "rated": None,
        }
        try:
            skill_id = await self._resolve_skill_id(slug)
            if skill_id is None:
                return dict(zero)

            like_rows = (
                client.table(_LIKES_TABLE)
                .select("device_or_user_id")
                .eq("skill_id", skill_id)
                .execute()
            )
            rating_rows = (
                client.table(_RATINGS_TABLE)
                .select("user_id, stars")
                .eq("skill_id", skill_id)
                .execute()
            )
            return _aggregate_social(
                (getattr(like_rows, "data", None) or []),
                (getattr(rating_rows, "data", None) or []),
                device_id=device_id,
                account_id=account_id,
            )
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("social.get_social failed for %r: %s", slug, exc)
            return dict(zero)


def _aggregate_social(
    like_rows: list[dict[str, Any]],
    rating_rows: list[dict[str, Any]],
    *,
    device_id: str,
    account_id: str | None,
) -> dict[str, Any]:
    """Fold raw like/rating rows into the public social aggregate.

    Pure (no I/O): kept module-level + side-effect-free so it is trivially
    unit-testable and reusable. ``liked`` is whether ``device_id`` appears in the
    likes; ``rated`` is ``account_id``'s stars (or None when signed out / absent).

    Args:
        like_rows: Raw ``likes`` rows (need ``device_or_user_id``).
        rating_rows: Raw ``ratings`` rows (need ``user_id`` + ``stars``).
        device_id: The viewing device's id.
        account_id: The viewing account's id, or None when signed out.

    Returns:
        The aggregate dict (``like_count``/``rating_count``/``avg_rating``/
        ``liked``/``rated``).
    """
    stars = [int(r["stars"]) for r in rating_rows if r.get("stars") is not None]
    liked = any(r.get("device_or_user_id") == device_id for r in like_rows)
    rated: int | None = None
    if account_id is not None:
        for r in rating_rows:
            if r.get("user_id") == account_id and r.get("stars") is not None:
                rated = int(r["stars"])
                break
    return {
        "like_count": len(like_rows),
        "rating_count": len(stars),
        "avg_rating": _avg(stars),
        "liked": liked,
        "rated": rated,
    }
