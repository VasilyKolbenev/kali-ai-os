"""Catalog client — thin Supabase wrapper with graceful degradation."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class CatalogClient:
    """Supabase-backed catalog client.

    Degrades gracefully when Supabase is not configured or supabase-py
    is not installed — all methods return empty results instead of raising.
    """

    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL", "")
        self._key = os.environ.get("SUPABASE_KEY", "")
        self._client: Any = None
        self._init_attempted = False

    @property
    def is_configured(self) -> bool:
        """True when both SUPABASE_URL and SUPABASE_KEY are set."""
        return bool(self._url and self._key)

    def _get_client(self) -> Any | None:
        """Lazily initialise the Supabase client.

        Returns:
            Supabase client instance, or None if unavailable.
        """
        if self._init_attempted:
            return self._client

        self._init_attempted = True
        if not self.is_configured:
            logger.debug("Supabase not configured — catalog offline")
            return None

        try:
            from supabase import create_client  # type: ignore[import-untyped]

            self._client = create_client(self._url, self._key)
        except ImportError:
            logger.warning("supabase-py not installed — catalog offline")
        except Exception as exc:
            logger.error("Failed to init Supabase client: %s", exc)

        return self._client

    async def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search catalog packages by keyword.

        Args:
            query: Full-text search string.
            category: Optional category filter.
            limit: Maximum number of results.

        Returns:
            List of matching package dicts, empty on error/offline.
        """
        client = self._get_client()
        if client is None:
            return []

        try:
            escaped = query.replace("%", "\\%").replace("_", "\\_")
            req = (
                client.table("packages")
                .select("*")
                .ilike("name", f"%{escaped}%")
                .limit(limit)
            )
            if category:
                req = req.eq("category", category)
            result = req.execute()
            return result.data or []
        except Exception as exc:
            logger.error("catalog.search failed: %s", exc)
            return []

    async def get_package(self, name: str) -> dict | None:
        """Fetch a single package by name.

        Args:
            name: Exact package name.

        Returns:
            Package dict or None if not found / offline.
        """
        client = self._get_client()
        if client is None:
            return None

        try:
            result = (
                client.table("packages").select("*").eq("name", name).single().execute()
            )
            return result.data
        except Exception as exc:
            logger.error("catalog.get_package failed for %r: %s", name, exc)
            return None

    async def publish(self, metadata: dict) -> dict:
        """Publish a new package to the catalog.

        Args:
            metadata: Package metadata dict (name, version, description, …).

        Returns:
            Inserted row dict, or empty dict on error/offline.
        """
        client = self._get_client()
        if client is None:
            return {}

        try:
            result = client.table("packages").insert(metadata).execute()
            return result.data[0] if result.data else {}
        except Exception as exc:
            logger.error("catalog.publish failed: %s", exc)
            return {}

    async def trending(self, limit: int = 10) -> list[dict]:
        """Return top packages sorted by download count.

        Args:
            limit: Maximum number of results.

        Returns:
            List of package dicts ordered by downloads desc, empty on error/offline.
        """
        client = self._get_client()
        if client is None:
            return []

        try:
            result = (
                client.table("packages")
                .select("*")
                .order("downloads", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("catalog.trending failed: %s", exc)
            return []
