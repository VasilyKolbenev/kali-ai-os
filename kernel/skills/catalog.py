"""Remote skills catalog — aggregates skills from public GitHub registries.

Data sources (configurable, defaults per Agent Skills ecosystem):
- anthropics/skills       — official reference skills (MIT)
- microsoft/skills        — Azure SDK skills (MIT)
- VoltAgent/awesome-agent-skills  — community catalog (curated)
- VasilyKolbenev/kali-skills      — our own KALI-specific skills

API design:
- CatalogSource: config for one registry (owner/repo/branch/skills_path)
- CatalogEntry: lightweight index card (no body loaded until needed)
- SkillsCatalog: aggregator with per-source caching

Network strategy:
- Use GitHub REST API: /repos/{owner}/{repo}/git/trees/{ref}?recursive=1
- Load only frontmatter (first 50 lines) for index, full body on demand
- Local cache in AppData to avoid rate limits (GitHub public API = 60 req/hr unauth)

This is READ-ONLY. Install lives in `kernel/skills/installer.py` (Phase 3.3).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests
import yaml

logger = logging.getLogger(__name__)

# Default remote sources — curated by KALI team
DEFAULT_SOURCES: list["CatalogSource"] = []  # populated after class def below


@dataclass
class CatalogSource:
    """Configuration for a remote skills registry.

    Two shapes supported:
    - ``source_type="github"`` (default): fetch SKILL.md from a GitHub repo tree.
    - ``source_type="aggregator_json"``: fetch pre-indexed JSON list from ``api_url``.
      Each item must carry ``owner``, ``repo``, ``name``, ``description`` at minimum.
    """

    id: str                       # stable identifier (e.g. "anthropic")
    label: str                    # human-readable (e.g. "Anthropic Official")
    owner: str = ""               # GitHub org/user (github sources only)
    repo: str = ""                # repo name (github sources only)
    ref: str = "main"             # branch/tag/SHA
    skills_path: str = "skills"   # subdirectory inside repo containing skill folders
    trust: str = "community"      # "official" | "verified" | "community"
    source_type: str = "github"   # "github" | "aggregator_json"
    api_url: str | None = None    # endpoint for aggregator_json sources

    @property
    def display_url(self) -> str:
        if self.source_type == "aggregator_json" and self.api_url:
            return self.api_url
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class CatalogEntry:
    """Lightweight index record for a remote skill (no body loaded)."""

    name: str                     # skill directory name (== SKILL.md name)
    description: str              # from frontmatter
    source_id: str                # CatalogSource.id
    source_label: str             # CatalogSource.label
    trust: str                    # from CatalogSource.trust
    repo_owner: str
    repo_name: str
    repo_ref: str
    skill_path: str               # path to skill dir inside repo
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_skill_md_url(self) -> str:
        """URL to the raw SKILL.md for direct download."""
        return (
            f"https://raw.githubusercontent.com/"
            f"{self.repo_owner}/{self.repo_name}/{self.repo_ref}/"
            f"{self.skill_path}/SKILL.md"
        )

    @property
    def web_url(self) -> str:
        return (
            f"https://github.com/{self.repo_owner}/{self.repo_name}/"
            f"tree/{self.repo_ref}/{self.skill_path}"
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["raw_skill_md_url"] = self.raw_skill_md_url
        d["web_url"] = self.web_url
        return d


DEFAULT_SOURCES = [
    CatalogSource(
        id="anthropic",
        label="Anthropic Official",
        owner="anthropics", repo="skills",
        trust="official",
    ),
    CatalogSource(
        id="microsoft",
        label="Microsoft Azure",
        owner="microsoft", repo="skills",
        skills_path="skills",
        trust="official",
    ),
    CatalogSource(
        id="voltagent",
        label="VoltAgent Community",
        owner="VoltAgent", repo="awesome-agent-skills",
        skills_path="skills",
        trust="community",
    ),
    CatalogSource(
        id="kali",
        label="KALI Skills",
        owner="VasilyKolbenev", repo="kali-skills",
        trust="verified",
    ),
    CatalogSource(
        id="neuraldeep",
        label="NeuralDeep (RU)",
        trust="community",
        source_type="aggregator_json",
        api_url="https://neuraldeep.ru/api/skills",
    ),
]


class CatalogFetchError(RuntimeError):
    """Raised when remote source cannot be queried (network, rate limit, 404)."""


def _parse_skill_md_frontmatter(content: str) -> dict[str, Any] | None:
    """Extract YAML frontmatter from a SKILL.md string. Returns None on failure."""
    try:
        from kernel.skills.loader import _split_frontmatter
        fm, _ = _split_frontmatter(content)
        return fm
    except Exception as exc:
        logger.debug("Skipping malformed SKILL.md: %s", exc)
        return None


class SkillsCatalog:
    """Aggregates remote skill catalogs with on-disk caching.

    Usage:
        catalog = SkillsCatalog()
        await catalog.refresh()
        for entry in catalog.search("weather"):
            print(entry.name, entry.source_label)
    """

    #: cache TTL (seconds) — 1 hour by default
    CACHE_TTL = 3600

    def __init__(
        self,
        sources: list[CatalogSource] | None = None,
        *,
        cache_dir: Path | None = None,
        http_timeout: float = 15.0,
    ) -> None:
        self._sources = sources if sources is not None else list(DEFAULT_SOURCES)
        self._http_timeout = http_timeout
        self._cache_dir = cache_dir or self._default_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, list[CatalogEntry]] = {}  # source_id → entries
        self._last_refresh: dict[str, float] = {}

    @staticmethod
    def _default_cache_dir() -> Path:
        from kernel.runtime_paths import appdata_dir
        return appdata_dir() / "catalog-cache"

    @property
    def sources(self) -> list[CatalogSource]:
        return list(self._sources)

    def _cache_file(self, source_id: str) -> Path:
        return self._cache_dir / f"{source_id}.json"

    def _load_cached(self, source: CatalogSource) -> list[CatalogEntry] | None:
        cache_path = self._cache_file(source.id)
        if not cache_path.is_file():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = data.get("cached_at", 0)
            if time.time() - cached_at > self.CACHE_TTL:
                return None
            entries = [CatalogEntry(**e) for e in data.get("entries", [])]
            logger.debug("Loaded %d entries from cache for %s", len(entries), source.id)
            return entries
        except Exception:
            logger.exception("Failed to load catalog cache for %s", source.id)
            return None

    def _save_cached(self, source_id: str, entries: list[CatalogEntry]) -> None:
        cache_path = self._cache_file(source_id)
        try:
            data = {
                "cached_at": time.time(),
                "entries": [asdict(e) for e in entries],
            }
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save catalog cache for %s", source_id)

    def _github_tree(self, source: CatalogSource) -> list[str]:
        """Fetch the recursive tree of a repo. Returns list of paths."""
        url = (
            f"https://api.github.com/repos/"
            f"{source.owner}/{source.repo}/git/trees/{source.ref}?recursive=1"
        )
        headers = {"Accept": "application/vnd.github+json"}
        # Allow optional token for higher rate limits
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            resp = requests.get(url, headers=headers, timeout=self._http_timeout)
        except requests.RequestException as exc:
            raise CatalogFetchError(f"Network error for {source.id}: {exc}") from exc

        if resp.status_code == 404:
            raise CatalogFetchError(f"Repo not found: {source.display_url}@{source.ref}")
        if resp.status_code == 403:
            # likely rate limit
            raise CatalogFetchError(
                f"GitHub API rate-limited for {source.id}. "
                "Set GITHUB_TOKEN env var to increase quota."
            )
        if resp.status_code != 200:
            raise CatalogFetchError(
                f"GitHub API error {resp.status_code} for {source.id}: {resp.text[:200]}"
            )

        tree = resp.json().get("tree", [])
        return [item["path"] for item in tree if item.get("type") == "blob"]

    def _fetch_skill_md(self, source: CatalogSource, skill_path: str) -> str | None:
        """Download a specific SKILL.md. Returns raw text or None on failure."""
        url = (
            f"https://raw.githubusercontent.com/"
            f"{source.owner}/{source.repo}/{source.ref}/{skill_path}"
        )
        try:
            resp = requests.get(url, timeout=self._http_timeout)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            pass
        return None

    def _fetch_aggregator_json(self, source: CatalogSource) -> list[CatalogEntry]:
        """Fetch pre-indexed catalog from a JSON API endpoint.

        Expected response: list of dicts with at least ``owner``, ``repo``, ``name``, ``description``.
        Optional: ``contentPath``, ``category``, ``tags``, ``installs``, ``githubStars``, ``featured``.
        """
        if not source.api_url:
            raise CatalogFetchError(f"Aggregator source {source.id} missing api_url")

        try:
            resp = requests.get(source.api_url, timeout=self._http_timeout)
        except requests.RequestException as exc:
            raise CatalogFetchError(f"Network error for {source.id}: {exc}") from exc

        if resp.status_code != 200:
            raise CatalogFetchError(
                f"Aggregator API error {resp.status_code} for {source.id}: {resp.text[:200]}"
            )

        try:
            items = resp.json()
        except ValueError as exc:
            raise CatalogFetchError(f"Invalid JSON from {source.id}: {exc}") from exc

        if not isinstance(items, list):
            raise CatalogFetchError(f"Expected JSON list from {source.id}, got {type(items).__name__}")

        entries: list[CatalogEntry] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            owner = str(item.get("owner") or "").strip()
            repo = str(item.get("repo") or "").strip()
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            if not (owner and repo and name and description):
                continue

            # contentPath — optional subdir inside repo (None/empty means repo root)
            content_path = (item.get("contentPath") or "").strip("/")
            skill_path = content_path if content_path else ""

            metadata: dict[str, Any] = {}
            for key in ("category", "tags", "installs", "githubStars", "featured", "trending24h"):
                if key in item and item[key] is not None:
                    metadata[key] = item[key]

            entries.append(CatalogEntry(
                name=name,
                description=description,
                source_id=source.id,
                source_label=source.label,
                trust=source.trust,
                repo_owner=owner,
                repo_name=repo,
                repo_ref=source.ref,
                skill_path=skill_path,
                metadata=metadata,
            ))

        logger.info("Indexed %d skills from %s (aggregator)", len(entries), source.id)
        return entries

    def _fetch_source(self, source: CatalogSource) -> list[CatalogEntry]:
        """Fetch and index all SKILL.md files in a source repo."""
        if source.source_type == "aggregator_json":
            return self._fetch_aggregator_json(source)

        logger.info("Fetching catalog from %s...", source.display_url)
        paths = self._github_tree(source)

        skill_md_paths = [p for p in paths if p.endswith("/SKILL.md")]
        if source.skills_path:
            # Filter to only skills under the configured path
            prefix = source.skills_path.strip("/") + "/"
            skill_md_paths = [p for p in skill_md_paths if p.startswith(prefix)]

        entries: list[CatalogEntry] = []
        for path in skill_md_paths:
            content = self._fetch_skill_md(source, path)
            if content is None:
                continue
            fm = _parse_skill_md_frontmatter(content)
            if fm is None or "name" not in fm or "description" not in fm:
                continue
            skill_dir_path = path[: -len("/SKILL.md")]
            entries.append(CatalogEntry(
                name=str(fm["name"]),
                description=str(fm["description"]),
                source_id=source.id,
                source_label=source.label,
                trust=source.trust,
                repo_owner=source.owner,
                repo_name=source.repo,
                repo_ref=source.ref,
                skill_path=skill_dir_path,
                license=fm.get("license"),
                compatibility=fm.get("compatibility"),
                metadata=dict(fm.get("metadata") or {}),
            ))

        logger.info("Indexed %d skills from %s", len(entries), source.id)
        return entries

    def refresh_source(self, source_id: str, *, force: bool = False) -> list[CatalogEntry]:
        """Refresh one source, using cache unless expired or ``force=True``."""
        source = next((s for s in self._sources if s.id == source_id), None)
        if source is None:
            raise ValueError(f"Unknown catalog source: {source_id}")

        if not force:
            cached = self._load_cached(source)
            if cached is not None:
                self._entries[source_id] = cached
                return cached

        try:
            entries = self._fetch_source(source)
        except CatalogFetchError as exc:
            logger.warning("Failed to refresh %s: %s", source.id, exc)
            # Keep previously cached data if any
            return self._entries.get(source_id, [])

        self._entries[source_id] = entries
        self._last_refresh[source_id] = time.time()
        self._save_cached(source_id, entries)
        return entries

    def refresh_all(self, *, force: bool = False) -> int:
        """Refresh all configured sources. Returns total entries indexed."""
        total = 0
        for source in self._sources:
            try:
                entries = self.refresh_source(source.id, force=force)
                total += len(entries)
            except Exception:
                logger.exception("Error refreshing source %s", source.id)
        return total

    def list_all(self) -> list[CatalogEntry]:
        """Combined entries across all sources (sorted by source trust, then name)."""
        trust_order = {"official": 0, "verified": 1, "community": 2}
        all_entries: list[CatalogEntry] = []
        for source in self._sources:
            all_entries.extend(self._entries.get(source.id, []))
        all_entries.sort(key=lambda e: (trust_order.get(e.trust, 99), e.name.lower()))
        return all_entries

    def list_by_source(self, source_id: str) -> list[CatalogEntry]:
        """Entries from a specific source."""
        return list(self._entries.get(source_id, []))

    def search(self, query: str) -> list[CatalogEntry]:
        """Substring search across name and description (case-insensitive)."""
        q = query.strip().lower()
        if not q:
            return self.list_all()
        results: list[CatalogEntry] = []
        for entry in self.list_all():
            if q in entry.name.lower() or q in entry.description.lower():
                results.append(entry)
        return results

    def get(self, source_id: str, name: str) -> CatalogEntry | None:
        """Lookup a specific skill by source and name."""
        for entry in self._entries.get(source_id, []):
            if entry.name == name:
                return entry
        return None
