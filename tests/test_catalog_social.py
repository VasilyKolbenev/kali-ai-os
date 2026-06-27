"""Tests for the §4 community social layer — like / rate / comment.

WS-3 Task 3.4. Drives the CatalogClient social methods that target the §4 social
tables (supabase/migrations/20260627115811_community_marketplace_schema.sql):

    * ``likes(skill_id, device_or_user_id, unique(skill_id, device_or_user_id))``
      — anonymous, device-scoped, 1 like per device (idempotent re-like = no-op),
      no sign-in;
    * ``ratings(skill_id, user_id, stars 1-5, unique(skill_id, user_id))`` —
      account-gated, 1 per user (upsert), 1-5 validated;
    * ``comments(id, skill_id, user_id, body, status, created_at)`` — account-gated
      insert (status defaults to ``pending`` moderation), public list shows only
      ``approved`` (RLS-enforced); body validation client-side;
    * ``get_social(slug)`` — aggregate like count + avg/`count` rating (+ whether
      THIS device liked / THIS account rated).

Identity rules (3.3): likes use ``identity.get_device_id()`` (anon device-id);
ratings + comments use ``identity.current_account_id()`` (the signed-in KALI
account) and HONESTLY return ``{"status": "sign-in required"}`` when signed out —
never a fake success.

Graceful degradation (same contract as the rest of CatalogClient): unconfigured /
offline Supabase yields ``[]`` / ``0`` / ``{"status": "unconfigured"}`` and never
raises. No live Supabase: the ``.table()`` chain is mocked (reusing the helpers
from tests/test_catalog_client.py). Tests NEVER touch the real %APPDATA% — the
identity layer is replaced by a fake, so no device-id/session file is written.
"""

from unittest.mock import MagicMock, patch

import pytest

from kernel.catalog.client import CatalogClient
from tests.test_catalog_client import _FakeIdentity, _make_supabase_mock


# ---------------------------------------------------------------------------
# Helpers — a configured client wired to a fake identity (no real appdata I/O)
# ---------------------------------------------------------------------------

def _social_client(
    supabase_mock: MagicMock,
    *,
    device_id: str = "dev-1",
    account_id: str | None = None,
) -> CatalogClient:
    """A configured CatalogClient with the Supabase mock + a fake identity.

    The fake identity means no test ever reads/writes the real device-id or
    session files under %APPDATA% (it is the same seam CatalogClient already
    swaps in tests/test_catalog_client.py).
    """
    with patch.dict(
        "os.environ",
        {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "key"},
    ):
        client = CatalogClient()
    client._client = supabase_mock
    client._init_attempted = True
    client._identity = _FakeIdentity(device_id=device_id, account_id=account_id)
    return client


def _skill_row(**over: object) -> dict:
    """A minimal `skills` lookup row (id + slug) for slug→id resolution."""
    row = {"id": "skill-uuid-1", "slug": "weather-bot"}
    row.update(over)
    return row


# ===========================================================================
# like / unlike — anon device-id, 1 per device (idempotent), no sign-in
# ===========================================================================

class TestLike:
    async def test_like_inserts_with_device_id_no_sign_in(self) -> None:
        # Signed OUT (account_id=None) — a like must still work (device-scoped).
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_skill_row()],
                "likes": [],  # no existing like for this device
            }
        )
        client = _social_client(mock, device_id="dev-7", account_id=None)

        result = await client.like("weather-bot")

        likes_chain = mock._chains["likes"]
        payload = likes_chain.insert.call_args[0][0]
        assert payload["skill_id"] == "skill-uuid-1"
        # §4: likes.device_or_user_id carries the anon device id.
        assert payload["device_or_user_id"] == "dev-7"
        assert result["status"] in ("ok", "liked")
        assert result.get("liked") is True

    async def test_like_is_idempotent_second_like_is_noop(self) -> None:
        # A like already exists for this device → a second like is a NO-OP, not
        # an error and not a duplicate insert (honest: liked stays True).
        existing = {
            "id": "like-1",
            "skill_id": "skill-uuid-1",
            "device_or_user_id": "dev-7",
        }
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "likes": [existing]}
        )
        client = _social_client(mock, device_id="dev-7")

        result = await client.like("weather-bot")

        # No duplicate insert — the unique(skill_id, device_or_user_id) would
        # reject it; the client checks first and skips.
        assert not mock._chains["likes"].insert.called
        assert result["status"] in ("ok", "liked", "noop")
        assert result.get("liked") is True

    async def test_unlike_removes_the_device_like(self) -> None:
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_skill_row()],
                "likes": [{"id": "like-1"}],
            }
        )
        client = _social_client(mock, device_id="dev-7")

        result = await client.unlike("weather-bot")

        likes_chain = mock._chains["likes"]
        # DELETE scoped to this skill + this device id.
        assert likes_chain.delete.called
        likes_chain.eq.assert_any_call("device_or_user_id", "dev-7")
        assert result["status"] in ("ok", "unliked")
        assert result.get("liked") is False

    async def test_like_unknown_skill_is_graceful(self) -> None:
        mock = _make_supabase_mock(table_rows={"skills": [], "likes": []})
        client = _social_client(mock, device_id="dev-7")

        result = await client.like("ghost")

        assert result["status"] in ("error", "unconfigured")
        assert not mock._chains["likes"].insert.called

    async def test_like_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()
        client._identity = _FakeIdentity(device_id="dev-7")
        assert await client.like("x") == {"status": "unconfigured"}

    async def test_unlike_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()
        client._identity = _FakeIdentity(device_id="dev-7")
        assert await client.unlike("x") == {"status": "unconfigured"}

    async def test_like_error_is_graceful(self) -> None:
        bad = MagicMock()
        bad.table.side_effect = RuntimeError("db down")
        client = _social_client(bad, device_id="dev-7")
        result = await client.like("x")
        assert result["status"] in ("error", "unconfigured")


# ===========================================================================
# set_rating — account-gated, 1-5, 1 per user (upsert), honest sign-in
# ===========================================================================

class TestSetRating:
    async def test_rating_signed_out_requires_sign_in(self) -> None:
        # No fake success: a signed-out rate is an honest refusal + no write.
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "ratings": []}
        )
        client = _social_client(mock, account_id=None)

        result = await client.set_rating("weather-bot", 5)

        assert result["status"] == "sign-in required"
        assert not mock._chains["ratings"].upsert.called

    async def test_rating_signed_in_upserts_stars(self) -> None:
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_skill_row()],
                "ratings": [{"id": "r1", "stars": 4}],
            }
        )
        client = _social_client(mock, account_id="acct-9")

        result = await client.set_rating("weather-bot", 4)

        ratings_chain = mock._chains["ratings"]
        payload = ratings_chain.upsert.call_args[0][0]
        assert payload["skill_id"] == "skill-uuid-1"
        assert payload["user_id"] == "acct-9"  # account-gated
        assert payload["stars"] == 4
        assert result["status"] in ("ok", "rated")
        assert result.get("stars") == 4

    @pytest.mark.parametrize("bad_stars", [0, 6, -1, 100])
    async def test_rating_rejects_out_of_range_stars(self, bad_stars: int) -> None:
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "ratings": []}
        )
        client = _social_client(mock, account_id="acct-9")

        result = await client.set_rating("weather-bot", bad_stars)

        # Invalid stars rejected BEFORE any write (validate at the boundary).
        assert result["status"] in ("error", "invalid")
        assert not mock._chains["ratings"].upsert.called

    async def test_rating_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()
        client._identity = _FakeIdentity(account_id="acct-9")
        assert await client.set_rating("x", 5) == {"status": "unconfigured"}

    async def test_rating_error_is_graceful(self) -> None:
        bad = MagicMock()
        bad.table.side_effect = RuntimeError("db down")
        client = _social_client(bad, account_id="acct-9")
        result = await client.set_rating("x", 5)
        assert result["status"] in ("error", "unconfigured")


# ===========================================================================
# post_comment — account-gated, body validation, default pending status
# ===========================================================================

class TestPostComment:
    async def test_comment_signed_out_requires_sign_in(self) -> None:
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "comments": []}
        )
        client = _social_client(mock, account_id=None)

        result = await client.post_comment("weather-bot", "great agent!")

        assert result["status"] == "sign-in required"
        assert not mock._chains["comments"].insert.called

    async def test_comment_signed_in_inserts_pending(self) -> None:
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_skill_row()],
                "comments": [{"id": "c1", "status": "pending"}],
            }
        )
        client = _social_client(mock, account_id="acct-9")

        result = await client.post_comment("weather-bot", "great agent!")

        comments_chain = mock._chains["comments"]
        payload = comments_chain.insert.call_args[0][0]
        assert payload["skill_id"] == "skill-uuid-1"
        assert payload["user_id"] == "acct-9"  # account-gated
        assert payload["body"] == "great agent!"
        # Moderation (3.7) is a seam: a fresh comment defaults to `pending`.
        assert payload["status"] == "pending"
        assert result["status"] in ("ok", "pending", "posted")

    async def test_comment_rejects_empty_body(self) -> None:
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "comments": []}
        )
        client = _social_client(mock, account_id="acct-9")

        result = await client.post_comment("weather-bot", "   ")

        assert result["status"] in ("error", "invalid")
        assert not mock._chains["comments"].insert.called

    async def test_comment_rejects_overlong_body(self) -> None:
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "comments": []}
        )
        client = _social_client(mock, account_id="acct-9")

        result = await client.post_comment("weather-bot", "x" * 5000)

        assert result["status"] in ("error", "invalid")
        assert not mock._chains["comments"].insert.called

    async def test_comment_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()
        client._identity = _FakeIdentity(account_id="acct-9")
        assert await client.post_comment("x", "hi") == {"status": "unconfigured"}


# ===========================================================================
# list_comments — approved-only (RLS enforces; client maps rows)
# ===========================================================================

class TestListComments:
    async def test_list_comments_returns_rows(self) -> None:
        rows = [
            {
                "id": "c1",
                "skill_id": "skill-uuid-1",
                "user_id": "acct-9",
                "body": "love it",
                "status": "approved",
                "created_at": "2026-06-27T00:00:00Z",
            }
        ]
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "comments": rows}
        )
        client = _social_client(mock, account_id="acct-9")

        result = await client.list_comments("weather-bot")

        assert isinstance(result, list)
        assert result[0]["body"] == "love it"
        # Defense-in-depth alongside RLS: the client filters to approved.
        mock._chains["comments"].eq.assert_any_call("status", "approved")

    async def test_list_comments_empty_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert await CatalogClient().list_comments("x") == []

    async def test_list_comments_unknown_skill_is_empty(self) -> None:
        mock = _make_supabase_mock(table_rows={"skills": [], "comments": []})
        client = _social_client(mock)
        assert await client.list_comments("ghost") == []


# ===========================================================================
# get_social — aggregate like count + avg/count rating (+ this device/account)
# ===========================================================================

class TestGetSocial:
    async def test_get_social_aggregates_counts(self) -> None:
        # 3 likes, 2 ratings (4 + 2 stars → avg 3.0). This device liked; this
        # account rated.
        likes_rows = [
            {"id": "l1", "device_or_user_id": "dev-7"},
            {"id": "l2", "device_or_user_id": "dev-x"},
            {"id": "l3", "device_or_user_id": "dev-y"},
        ]
        ratings_rows = [
            {"id": "r1", "user_id": "acct-9", "stars": 4},
            {"id": "r2", "user_id": "acct-z", "stars": 2},
        ]
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_skill_row()],
                "likes": likes_rows,
                "ratings": ratings_rows,
            }
        )
        client = _social_client(mock, device_id="dev-7", account_id="acct-9")

        social = await client.get_social("weather-bot")

        assert social["like_count"] == 3
        assert social["rating_count"] == 2
        assert social["avg_rating"] == pytest.approx(3.0)
        assert social["liked"] is True  # dev-7 is in the likes rows
        assert social["rated"] == 4  # acct-9's stars

    async def test_get_social_zero_when_no_social_rows(self) -> None:
        mock = _make_supabase_mock(
            table_rows={"skills": [_skill_row()], "likes": [], "ratings": []}
        )
        client = _social_client(mock, device_id="dev-7", account_id="acct-9")

        social = await client.get_social("weather-bot")

        assert social["like_count"] == 0
        assert social["rating_count"] == 0
        assert social["avg_rating"] == 0
        assert social["liked"] is False
        assert social["rated"] is None

    async def test_get_social_signed_out_rated_is_none(self) -> None:
        # Signed out → no account → `rated` is None but likes/aggregates still work.
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_skill_row()],
                "likes": [{"id": "l1", "device_or_user_id": "dev-7"}],
                "ratings": [{"id": "r1", "user_id": "acct-9", "stars": 5}],
            }
        )
        client = _social_client(mock, device_id="dev-7", account_id=None)

        social = await client.get_social("weather-bot")

        assert social["like_count"] == 1
        assert social["liked"] is True
        assert social["rated"] is None

    async def test_get_social_unconfigured_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        social = await CatalogClient().get_social("x")
        assert social["status"] == "unconfigured"
        assert social["like_count"] == 0
        assert social["rating_count"] == 0

    async def test_get_social_unknown_skill_is_zero(self) -> None:
        mock = _make_supabase_mock(
            table_rows={"skills": [], "likes": [], "ratings": []}
        )
        client = _social_client(mock)
        social = await client.get_social("ghost")
        assert social["like_count"] == 0
        assert social["rating_count"] == 0


# ===========================================================================
# Graceful degradation — supabase-py not installed
# ===========================================================================

class TestSocialDegradation:
    async def test_like_unconfigured_when_import_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "key")
        client = CatalogClient()
        client._identity = _FakeIdentity(device_id="dev-7")

        with patch.dict(sys.modules, {"supabase": None}):
            result = await client.like("x")

        assert result == {"status": "unconfigured"}
