"""Catalog client — thin Supabase wrapper with graceful degradation."""

import logging
import os
from pathlib import Path
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

    async def local_search(
        self,
        query: str,
        agents_dir: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Search locally installed agents/skills by name/description.

        Args:
            query: Search string (empty returns all).
            agents_dir: Path to agents directory. Defaults to agents/.

        Returns:
            List of matching package dicts with installed=True.
        """
        if agents_dir is None:
            agents_dir = Path("agents")
        results: list[dict[str, Any]] = []
        if not agents_dir.is_dir():
            return results
        query_lower = query.lower()
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            manifest_path = agent_dir / "manifest.yaml"
            if not manifest_path.exists():
                continue
            try:
                import yaml  # type: ignore[import-untyped]

                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f)
                name: str = manifest.get("name", "")
                desc: str = manifest.get("description", "")
                if query_lower and query_lower not in name.lower() and query_lower not in desc.lower():
                    continue
                results.append({
                    "name": name,
                    "description": desc,
                    "type": "skill" if (agent_dir / "skill.yaml").exists() else "agent",
                    "category": "local",
                    "downloads": 0,
                    "rating_avg": 0,
                    "trust_level": "official",
                    "version": manifest.get("version", "1.0.0"),
                    "installed": True,
                })
            except Exception:
                continue
        return results

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
