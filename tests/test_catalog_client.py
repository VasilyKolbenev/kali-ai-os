"""Tests for kernel.catalog.client — CatalogClient with mocked Supabase."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from kernel.catalog.client import CatalogClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_supabase_mock(rows: list[dict] | None = None) -> MagicMock:
    """Build a Supabase client mock whose execute() returns the given rows."""
    rows = rows or []
    result = MagicMock()
    result.data = rows

    # Chain: .table().select/insert/...().eq/ilike/...().execute()
    chain = MagicMock()
    chain.execute.return_value = result
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.ilike.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.single.return_value = chain

    client_mock = MagicMock()
    client_mock.table.return_value = chain
    return client_mock


def _configured_client(supabase_mock: MagicMock) -> CatalogClient:
    """Return a CatalogClient that believes Supabase is configured and uses supabase_mock."""
    with patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "key"}):
        client = CatalogClient()

    # Inject mock directly — bypasses real network
    client._client = supabase_mock
    client._init_attempted = True
    return client


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured:
    def test_configured_when_env_set(self) -> None:
        with patch.dict("os.environ", {"SUPABASE_URL": "https://x", "SUPABASE_KEY": "k"}):
            assert CatalogClient().is_configured is True

    def test_not_configured_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert CatalogClient().is_configured is False


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    async def test_search_returns_results(self) -> None:
        """search() returns list of matching packages."""
        rows = [{"name": "weather-agent", "category": "tools"}]
        client = _configured_client(_make_supabase_mock(rows))

        results = await client.search("weather")

        assert results == rows

    async def test_search_empty_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """search() returns [] when Supabase is not configured."""
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()

        results = await client.search("anything")

        assert results == []

    async def test_search_with_category_filter(self) -> None:
        """search() passes category filter to Supabase query."""
        mock = _make_supabase_mock([{"name": "gpt-agent", "category": "ai"}])
        client = _configured_client(mock)

        results = await client.search("gpt", category="ai")

        assert results[0]["category"] == "ai"
        # .eq("category", "ai") must have been called on the chain
        mock.table.return_value.eq.assert_called_with("category", "ai")

    async def test_search_returns_empty_on_supabase_error(self) -> None:
        """search() returns [] when Supabase raises an exception."""
        bad_mock = MagicMock()
        bad_mock.table.side_effect = RuntimeError("db down")
        client = _configured_client(bad_mock)

        results = await client.search("query")

        assert results == []


# ---------------------------------------------------------------------------
# get_package
# ---------------------------------------------------------------------------

class TestGetPackage:
    async def test_get_package_returns_data(self) -> None:
        """get_package() returns the matching package dict."""
        pkg = {"name": "todo-agent", "version": "1.0.0"}
        # .single() returns data as a plain dict (not a list)
        mock = _make_supabase_mock()
        mock.table.return_value.execute.return_value.data = pkg
        client = _configured_client(mock)

        result = await client.get_package("todo-agent")

        assert result == pkg

    async def test_get_package_returns_none_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()

        assert await client.get_package("any") is None

    async def test_get_package_returns_none_on_error(self) -> None:
        bad_mock = MagicMock()
        bad_mock.table.side_effect = Exception("oops")
        client = _configured_client(bad_mock)

        assert await client.get_package("any") is None


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

class TestPublish:
    async def test_publish_returns_inserted_row(self) -> None:
        """publish() returns the newly inserted package dict."""
        metadata = {"name": "new-agent", "version": "0.1.0"}
        client = _configured_client(_make_supabase_mock([metadata]))

        result = await client.publish(metadata)

        assert result == metadata

    async def test_publish_returns_empty_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()

        result = await client.publish({"name": "x"})

        assert result == {}

    async def test_publish_returns_empty_on_error(self) -> None:
        bad_mock = MagicMock()
        bad_mock.table.side_effect = Exception("insert failed")
        client = _configured_client(bad_mock)

        result = await client.publish({"name": "x"})

        assert result == {}


# ---------------------------------------------------------------------------
# trending
# ---------------------------------------------------------------------------

class TestTrending:
    async def test_trending_returns_sorted_by_downloads(self) -> None:
        """trending() returns packages from Supabase (ordered by DB query)."""
        rows = [
            {"name": "popular-agent", "downloads": 9000},
            {"name": "less-popular", "downloads": 100},
        ]
        client = _configured_client(_make_supabase_mock(rows))

        results = await client.trending(limit=2)

        assert results == rows
        assert results[0]["downloads"] > results[1]["downloads"]

    async def test_trending_empty_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = CatalogClient()

        assert await client.trending() == []

    async def test_trending_calls_order_desc(self) -> None:
        """trending() calls .order('downloads', desc=True) on the query."""
        mock = _make_supabase_mock([])
        client = _configured_client(mock)

        await client.trending()

        mock.table.return_value.order.assert_called_with("downloads", desc=True)


# ---------------------------------------------------------------------------
# Graceful degradation when supabase-py not installed
# ---------------------------------------------------------------------------

class TestSupabaseNotInstalled:
    async def test_search_returns_empty_when_import_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """search() returns [] when supabase-py import raises ImportError."""
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "key")

        client = CatalogClient()

        # Simulate supabase-py not installed by blocking the import
        with patch.dict(sys.modules, {"supabase": None}):
            results = await client.search("test")

        assert results == []

    async def test_get_client_logs_warning_on_import_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warning is logged when supabase-py is unavailable."""
        import logging

        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "key")

        client = CatalogClient()

        with caplog.at_level(logging.WARNING, logger="kernel.catalog.client"):
            with patch.dict(sys.modules, {"supabase": None}):
                client._get_client()

        assert any("supabase" in r.message.lower() for r in caplog.records)
