"""Tests for kernel.catalog.client — CatalogClient against the §4 marketplace model.

The §4 schema (supabase/migrations/20260627115811_community_marketplace_schema.sql)
replaces the flat `packages` prototype with normalized tables: `creators`, `skills`
(status pending/approved/flagged/removed), `installs`, etc. These tests drive the
CatalogClient rewrite that targets `skills`/`creators`/`installs` — read methods
filter to status='approved', publish inserts a `pending` row + uploads the bundle to
Storage, creator CRUD is handle + self-declared socials (display-only), and install
records an attribution row + increments `skills.install_count`.

No live Supabase: the Supabase client (supabase-py) is mocked via the same
.table()/.storage chain pattern the prototype tests used. The graceful-degradation
contract is preserved — unconfigured/offline reads return []/None and writes return a
clear "unconfigured" result, never an exception.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from kernel.catalog.client import CatalogClient, Skill


# ---------------------------------------------------------------------------
# Helpers — Supabase client mock (table + storage chains)
# ---------------------------------------------------------------------------

def _make_table_chain(rows: list[dict] | None = None) -> MagicMock:
    """Build a query-builder chain whose execute() returns the given rows.

    Mirrors supabase-py semantics: the plain ``.execute().data`` is the row LIST,
    while ``.single()/.maybe_single().execute().data`` is a SINGLE row dict (or None
    when empty). The same ``chain`` is returned by every fluent verb so calls compose,
    EXCEPT ``single``/``maybe_single`` which yield a sub-chain with the dict result.
    """
    rows = rows or []
    result = MagicMock()
    result.data = rows

    chain = MagicMock()
    chain.execute.return_value = result
    # Fluent verbs return the same chain so calls compose.
    for verb in ("select", "insert", "update", "upsert", "ilike", "eq",
                 "neq", "order", "limit"):
        getattr(chain, verb).return_value = chain

    # single()/maybe_single() collapse the list to one dict (or None).
    single_result = MagicMock()
    single_result.data = rows[0] if rows else None
    single_chain = MagicMock()
    single_chain.execute.return_value = single_result
    for verb in ("select", "insert", "update", "upsert", "ilike", "eq",
                 "neq", "order", "limit"):
        getattr(single_chain, verb).return_value = single_chain
    chain.single.return_value = single_chain
    chain.maybe_single.return_value = single_chain
    return chain


def _make_supabase_mock(
    rows: list[dict] | None = None,
    *,
    table_rows: dict[str, list[dict]] | None = None,
) -> MagicMock:
    """Build a Supabase client mock.

    Args:
        rows: rows returned by EVERY table's execute() (simple single-table tests).
        table_rows: optional per-table-name override mapping table -> rows, so a
            test can make `skills` and `installs` return different data.
    """
    client_mock = MagicMock()

    if table_rows is not None:
        chains = {name: _make_table_chain(r) for name, r in table_rows.items()}

        def _table(name: str) -> MagicMock:
            return chains.setdefault(name, _make_table_chain([]))

        client_mock.table.side_effect = _table
        client_mock._chains = chains  # exposed for assertions
    else:
        chain = _make_table_chain(rows)
        client_mock.table.return_value = chain

    # Storage chain: client.storage.from_(bucket).upload(path, data, opts)
    storage_bucket = MagicMock()
    storage_bucket.upload.return_value = MagicMock()
    client_mock.storage.from_.return_value = storage_bucket

    return client_mock


def _configured_client(supabase_mock: MagicMock) -> CatalogClient:
    """A CatalogClient that believes Supabase is configured, wired to supabase_mock."""
    with patch.dict(
        "os.environ",
        {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "key"},
    ):
        client = CatalogClient()
    client._client = supabase_mock
    client._init_attempted = True
    return client


def _approved(**over: object) -> dict:
    """A minimal approved `skills` row (§4 field names)."""
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "slug": "weather-bot",
        "name": "Weather Bot",
        "description": "tells the weather",
        "category": "tools",
        "creator_id": "22222222-2222-2222-2222-222222222222",
        "bundle_path": "bundles/weather-bot.kali-agent",
        "version": "1.0.0",
        "template": None,
        "format": "SKILL.md",
        "status": "approved",
        "install_count": 42,
    }
    row.update(over)
    return row


# ===========================================================================
# is_configured / graceful degradation surface
# ===========================================================================

class TestIsConfigured:
    def test_configured_when_env_set(self) -> None:
        with patch.dict("os.environ", {"SUPABASE_URL": "https://x", "SUPABASE_KEY": "k"}):
            assert CatalogClient().is_configured is True

    def test_not_configured_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert CatalogClient().is_configured is False


# ===========================================================================
# Skill mapping (row -> typed dataclass -> dict)
# ===========================================================================

class TestSkillMapping:
    def test_from_row_maps_section4_fields(self) -> None:
        skill = Skill.from_row(_approved())
        assert skill.slug == "weather-bot"
        assert skill.name == "Weather Bot"
        assert skill.category == "tools"
        assert skill.creator_id == "22222222-2222-2222-2222-222222222222"
        assert skill.bundle_path == "bundles/weather-bot.kali-agent"
        assert skill.status == "approved"
        assert skill.install_count == 42

    def test_from_row_tolerates_missing_optional_fields(self) -> None:
        # A trending_skills view row has no description/bundle_path/format.
        skill = Skill.from_row(
            {"slug": "x", "name": "X", "category": None, "install_count": 3}
        )
        assert skill.slug == "x"
        assert skill.description is None
        assert skill.bundle_path is None
        assert skill.install_count == 3

    def test_to_dict_roundtrips_name_for_consumers(self) -> None:
        # kernel/main.py dedups cloud results on the "name" key, so the dict
        # form MUST carry name + slug.
        d = Skill.from_row(_approved()).to_dict()
        assert d["name"] == "Weather Bot"
        assert d["slug"] == "weather-bot"
        assert d["install_count"] == 42


# ===========================================================================
# search — reads `skills` WHERE status='approved'
# ===========================================================================

class TestSearch:
    async def test_search_returns_approved_skills_mapped(self) -> None:
        client = _configured_client(_make_supabase_mock([_approved()]))

        results = await client.search("weather")

        assert isinstance(results, list)
        assert results[0]["slug"] == "weather-bot"
        assert results[0]["name"] == "Weather Bot"

    async def test_search_filters_to_approved_status(self) -> None:
        mock = _make_supabase_mock([_approved()])
        client = _configured_client(mock)

        await client.search("weather")

        # status='approved' must be applied (defense in depth alongside RLS).
        mock.table.return_value.eq.assert_any_call("status", "approved")
        mock.table.assert_called_with("skills")

    async def test_search_with_category_filter(self) -> None:
        mock = _make_supabase_mock([_approved(category="ai")])
        client = _configured_client(mock)

        results = await client.search("gpt", category="ai")

        assert results[0]["category"] == "ai"
        mock.table.return_value.eq.assert_any_call("category", "ai")

    async def test_search_empty_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()

        assert await client.search("anything") == []

    async def test_search_returns_empty_on_supabase_error(self) -> None:
        bad = MagicMock()
        bad.table.side_effect = RuntimeError("db down")
        client = _configured_client(bad)

        assert await client.search("query") == []


# ===========================================================================
# browse — approved skills (no query)
# ===========================================================================

class TestBrowse:
    async def test_browse_returns_approved_skills(self) -> None:
        mock = _make_supabase_mock([_approved(), _approved(slug="b", name="B")])
        client = _configured_client(mock)

        results = await client.browse()

        assert {r["slug"] for r in results} == {"weather-bot", "b"}
        mock.table.return_value.eq.assert_any_call("status", "approved")

    async def test_browse_empty_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert await CatalogClient().browse() == []


# ===========================================================================
# trending — reads the trending_skills view (already approved-only)
# ===========================================================================

class TestTrending:
    async def test_trending_reads_trending_view(self) -> None:
        rows = [
            {"slug": "hot", "name": "Hot", "install_count": 900, "trending_score": 88.0},
            {"slug": "warm", "name": "Warm", "install_count": 10, "trending_score": 3.0},
        ]
        mock = _make_supabase_mock(rows)
        client = _configured_client(mock)

        results = await client.trending(limit=2)

        assert [r["slug"] for r in results] == ["hot", "warm"]
        mock.table.assert_called_with("trending_skills")

    async def test_trending_empty_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert await CatalogClient().trending() == []


# ===========================================================================
# get_skill — single approved skill by slug
# ===========================================================================

class TestGetSkill:
    async def test_get_skill_returns_mapped_dict(self) -> None:
        # get_skill() uses .maybe_single() → set the single-row sub-chain result.
        mock = _make_supabase_mock([_approved()])
        client = _configured_client(mock)

        result = await client.get_skill("weather-bot")

        assert result is not None
        assert result["slug"] == "weather-bot"
        mock.table.return_value.eq.assert_any_call("slug", "weather-bot")
        mock.table.return_value.eq.assert_any_call("status", "approved")

    async def test_get_skill_none_when_missing(self) -> None:
        mock = _make_supabase_mock([])  # empty → maybe_single yields None
        client = _configured_client(mock)

        assert await client.get_skill("nope") is None

    async def test_get_skill_none_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert await CatalogClient().get_skill("any") is None

    async def test_get_skill_none_on_error(self) -> None:
        bad = MagicMock()
        bad.table.side_effect = Exception("oops")
        client = _configured_client(bad)
        assert await client.get_skill("any") is None


# ===========================================================================
# publish_skill — upload bundle to Storage + insert a `pending` skills row
# ===========================================================================

class TestPublishSkill:
    async def test_publish_uploads_bundle_and_inserts_pending_row(self) -> None:
        inserted = _approved(status="pending", install_count=0)
        mock = _make_supabase_mock([inserted])
        client = _configured_client(mock)

        result = await client.publish_skill(
            slug="weather-bot",
            name="Weather Bot",
            creator_id="22222222-2222-2222-2222-222222222222",
            bundle=b"PK\x03\x04 fake zip bytes",
            description="tells the weather",
            category="tools",
        )

        # bundle uploaded to Storage
        assert mock.storage.from_.called
        bucket = mock.storage.from_.return_value
        assert bucket.upload.called
        up_args, up_kwargs = bucket.upload.call_args
        # the storage path is derived from the slug
        assert any("weather-bot" in str(a) for a in up_args) or any(
            "weather-bot" in str(v) for v in up_kwargs.values()
        )

        # row inserted into `skills`
        mock.table.assert_any_call("skills")
        insert_payload = mock.table.return_value.insert.call_args[0][0]
        assert insert_payload["slug"] == "weather-bot"
        assert insert_payload["creator_id"] == "22222222-2222-2222-2222-222222222222"
        assert insert_payload["bundle_path"]  # points at the uploaded object
        # Moderation lifecycle is 3.7: gate is a seam → default status is pending.
        assert insert_payload["status"] == "pending"

        assert result["status"] in ("pending", "approved")
        assert result["slug"] == "weather-bot"

    async def test_publish_status_approved_when_gate_passes(self) -> None:
        inserted = _approved(status="approved", install_count=0)
        mock = _make_supabase_mock([inserted])
        client = _configured_client(mock)

        # The safety/heuristic gate is a SEAM (3.7). Injecting a passing gate
        # flips the inserted status to approved.
        result = await client.publish_skill(
            slug="safe",
            name="Safe",
            creator_id="22222222-2222-2222-2222-222222222222",
            bundle=b"zip",
            safety_gate=lambda **_: True,
        )

        insert_payload = mock.table.return_value.insert.call_args[0][0]
        assert insert_payload["status"] == "approved"
        assert result["status"] == "approved"

    async def test_publish_returns_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()

        result = await client.publish_skill(
            slug="x",
            name="X",
            creator_id="c",
            bundle=b"zip",
        )

        assert result == {"status": "unconfigured"}

    async def test_publish_returns_unconfigured_on_error(self) -> None:
        bad = MagicMock()
        bad.storage.from_.side_effect = Exception("storage down")
        client = _configured_client(bad)

        result = await client.publish_skill(
            slug="x", name="X", creator_id="c", bundle=b"zip"
        )

        assert result == {"status": "unconfigured"}


# ===========================================================================
# Creator profile CRUD — handle + self-declared socials (display strings)
# ===========================================================================

class TestCreator:
    async def test_get_creator_by_handle(self) -> None:
        row = {
            "id": "22222222-2222-2222-2222-222222222222",
            "handle": "vasily",
            "socials": {"tiktok": "@vasily"},
        }
        mock = _make_supabase_mock([row])  # get_creator() uses .maybe_single()
        client = _configured_client(mock)

        result = await client.get_creator("vasily")

        assert result == row
        mock.table.assert_called_with("creators")
        mock.table.return_value.eq.assert_any_call("handle", "vasily")

    async def test_get_creator_none_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert await CatalogClient().get_creator("vasily") is None

    async def test_upsert_creator_writes_handle_and_socials(self) -> None:
        row = {"id": "c1", "handle": "vasily", "socials": {"tiktok": "@v"}}
        mock = _make_supabase_mock([row])
        client = _configured_client(mock)

        result = await client.upsert_creator(
            creator_id="c1",
            handle="vasily",
            socials={"tiktok": "@v"},
        )

        mock.table.assert_called_with("creators")
        payload = mock.table.return_value.upsert.call_args[0][0]
        assert payload["id"] == "c1"
        assert payload["handle"] == "vasily"
        assert payload["socials"] == {"tiktok": "@v"}
        assert result == row

    async def test_upsert_creator_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        result = await CatalogClient().upsert_creator(
            creator_id="c1", handle="v", socials={}
        )
        assert result == {"status": "unconfigured"}


# ===========================================================================
# record_install — insert installs row + increment skills.install_count
# ===========================================================================

class TestRecordInstall:
    async def test_record_install_inserts_row_and_increments_count(self) -> None:
        # `skills` lookup returns current count=42; installs insert succeeds.
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_approved(install_count=42)],
                "installs": [{"id": "ins1"}],
            }
        )
        client = _configured_client(mock)

        result = await client.record_install(
            slug="weather-bot",
            device_id="device-abc",
            creator_attrib="22222222-2222-2222-2222-222222222222",
        )

        # installs row inserted with attribution + device id (no PII beyond opaque id)
        installs_chain = mock._chains["installs"]
        install_payload = installs_chain.insert.call_args[0][0]
        assert install_payload["device_id"] == "device-abc"
        assert install_payload["creator_attrib"] == (
            "22222222-2222-2222-2222-222222222222"
        )
        assert install_payload["skill_id"] == _approved()["id"]

        # skills.install_count incremented (read-modify-write: 42 -> 43)
        skills_chain = mock._chains["skills"]
        update_payload = skills_chain.update.call_args[0][0]
        assert update_payload["install_count"] == 43

        assert result["status"] == "ok"
        assert result["install_count"] == 43

    async def test_record_install_unconfigured_when_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        result = await CatalogClient().record_install(
            slug="x", device_id="d"
        )
        assert result == {"status": "unconfigured"}

    async def test_record_install_unconfigured_when_skill_missing(self) -> None:
        # Unknown slug → no skills row → cannot attribute → graceful result.
        mock = _make_supabase_mock(
            table_rows={"skills": [], "installs": [{"id": "ins1"}]}
        )
        client = _configured_client(mock)

        result = await client.record_install(slug="ghost", device_id="d")

        assert result["status"] in ("unconfigured", "error")

    async def test_record_install_error_is_graceful(self) -> None:
        bad = MagicMock()
        bad.table.side_effect = Exception("db down")
        client = _configured_client(bad)

        result = await client.record_install(slug="x", device_id="d")

        assert result["status"] in ("unconfigured", "error")


# ===========================================================================
# local_search — PRESERVED from the prototype (kernel/main.py depends on it)
# ===========================================================================

class TestLocalSearch:
    async def test_local_search_returns_empty_for_missing_dir(self, tmp_path) -> None:
        client = CatalogClient()
        results = await client.local_search("x", tmp_path / "nope")
        assert results == []


# ===========================================================================
# Graceful degradation — supabase-py not installed
# ===========================================================================

class TestSupabaseNotInstalled:
    async def test_search_returns_empty_when_import_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "key")
        client = CatalogClient()

        with patch.dict(sys.modules, {"supabase": None}):
            results = await client.search("test")

        assert results == []

    async def test_publish_unconfigured_when_import_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "key")
        client = CatalogClient()

        with patch.dict(sys.modules, {"supabase": None}):
            result = await client.publish_skill(
                slug="x", name="X", creator_id="c", bundle=b"zip"
            )

        assert result == {"status": "unconfigured"}

    async def test_get_client_logs_warning_on_import_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "key")
        client = CatalogClient()

        with caplog.at_level(logging.WARNING, logger="kernel.catalog.client"):
            with patch.dict(sys.modules, {"supabase": None}):
                client._get_client()

        assert any("supabase" in r.message.lower() for r in caplog.records)


# ===========================================================================
# Identity wiring (3.3) — device-id auto-supplied for installs, account-id
# (auth.uid) auto-supplied for publish; explicit param override preserved.
# ===========================================================================

class _FakeIdentity:
    """Stand-in for kernel.catalog.identity.CommunityIdentity for wiring tests."""

    def __init__(self, *, device_id: str = "dev-fake", account_id: str | None = None):
        self._device_id = device_id
        self._account_id = account_id

    def get_device_id(self) -> str:
        return self._device_id

    def current_account_id(self) -> str | None:
        return self._account_id

    def is_signed_in(self) -> bool:
        return self._account_id is not None


class TestIdentityWiring:
    async def test_record_install_auto_supplies_device_id(self) -> None:
        # No device_id passed → CatalogClient pulls it from the identity layer.
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_approved(install_count=5)],
                "installs": [{"id": "ins1"}],
            }
        )
        client = _configured_client(mock)
        client._identity = _FakeIdentity(device_id="auto-device-7")

        result = await client.record_install(slug="weather-bot")

        install_payload = mock._chains["installs"].insert.call_args[0][0]
        assert install_payload["device_id"] == "auto-device-7"
        assert result["status"] == "ok"

    async def test_record_install_explicit_device_id_overrides(self) -> None:
        mock = _make_supabase_mock(
            table_rows={
                "skills": [_approved(install_count=5)],
                "installs": [{"id": "ins1"}],
            }
        )
        client = _configured_client(mock)
        client._identity = _FakeIdentity(device_id="auto-device-7")

        await client.record_install(slug="weather-bot", device_id="explicit-9")

        install_payload = mock._chains["installs"].insert.call_args[0][0]
        assert install_payload["device_id"] == "explicit-9"

    async def test_publish_auto_supplies_creator_id_from_session(self) -> None:
        inserted = _approved(status="pending", install_count=0)
        mock = _make_supabase_mock([inserted])
        client = _configured_client(mock)
        client._identity = _FakeIdentity(account_id="acct-uid-42")

        # creator_id omitted → taken from the signed-in account.
        result = await client.publish_skill(
            slug="weather-bot",
            name="Weather Bot",
            bundle=b"zip",
        )

        insert_payload = mock.table.return_value.insert.call_args[0][0]
        assert insert_payload["creator_id"] == "acct-uid-42"
        assert result["slug"] == "weather-bot"

    async def test_publish_explicit_creator_id_overrides_session(self) -> None:
        inserted = _approved(status="pending", install_count=0)
        mock = _make_supabase_mock([inserted])
        client = _configured_client(mock)
        client._identity = _FakeIdentity(account_id="acct-uid-42")

        await client.publish_skill(
            slug="weather-bot",
            name="Weather Bot",
            creator_id="explicit-creator",
            bundle=b"zip",
        )

        insert_payload = mock.table.return_value.insert.call_args[0][0]
        assert insert_payload["creator_id"] == "explicit-creator"

    async def test_publish_requires_sign_in_when_no_session(self) -> None:
        # Signed-out + no explicit creator_id → honest refusal, NOT a silent
        # anon publish. Nothing is uploaded or inserted.
        mock = _make_supabase_mock([_approved(status="pending")])
        client = _configured_client(mock)
        client._identity = _FakeIdentity(account_id=None)  # signed out

        result = await client.publish_skill(
            slug="weather-bot",
            name="Weather Bot",
            bundle=b"zip",
        )

        assert result["status"] == "sign-in required"
        assert not mock.storage.from_.called  # nothing uploaded
        assert not mock.table.return_value.insert.called  # nothing inserted

    async def test_record_install_still_works_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Identity wiring must not break the graceful-degradation contract.
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        result = await CatalogClient().record_install(slug="x", device_id="d")
        assert result == {"status": "unconfigured"}
