"""Catalog client — Supabase wrapper for the §4 community marketplace model.

Targets the normalized §4 schema (supabase/migrations/*.sql): the `skills` catalog
(status pending/approved/flagged/removed), `creators` profiles (handle + self-declared
socials, display-only), and `installs` (attribution + trending input). It REPLACES the
2026-04-13 flat-`packages` prototype.

Scope (WS-3 Task 3.2 — catalog CRUD only):
    * read approved skills (``search`` / ``browse`` / ``trending`` / ``get_skill``),
    * ``publish_skill`` — upload the bundle to Storage + insert a ``pending`` row,
    * creator profile CRUD (``get_creator`` / ``upsert_creator``),
    * ``record_install`` — attribution row + ``skills.install_count`` increment,
    * ``local_search`` — locally installed agents (preserved from the prototype).

Out of scope (separate tasks): social like/rate/comment (3.4), identity/auth wiring
(3.3 — methods accept ``device_id`` / ``creator_id`` params), the moderation lifecycle
(3.7 — the publish safety gate is a SEAM, defaulting to ``status='pending'``).

Graceful degradation (preserved contract): when Supabase is unconfigured or supabase-py
is unavailable, reads return ``[]`` / ``None`` and writes return ``{"status":
"unconfigured"}`` — never an exception. The «Сообщество» UI relies on this to
degrade to the GitHub-curated set + locally installed skills.
"""

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from kernel.catalog.identity import CommunityIdentity
from kernel.catalog.moderation import ModerationMixin, auto_approve_gate
from kernel.catalog.social import SocialMixin

logger = logging.getLogger(__name__)

# §4 table / view / storage names (single source of truth for the mapping).
_SKILLS_TABLE = "skills"
_TRENDING_VIEW = "trending_skills"
_CREATORS_TABLE = "creators"
_INSTALLS_TABLE = "installs"
_BUNDLE_BUCKET = "skill-bundles"
_STATUS_APPROVED = "approved"
_STATUS_PENDING = "pending"
_UNCONFIGURED: dict[str, str] = {"status": "unconfigured"}

# Columns selected for a catalog skill (the trending_skills view is a subset, so
# reads tolerate missing keys via Skill.from_row).
_SKILL_COLUMNS = (
    "id, slug, name, description, category, creator_id, bundle_path, "
    "version, template, format, status, install_count, created_at, updated_at"
)


@dataclass(frozen=True)
class Skill:
    """A catalog skill row mapped from the §4 ``skills`` table (or trending view).

    Attributes:
        slug: Stable URL/identity key (``skills.slug``).
        name: Human-readable title.
        description: Optional long description.
        category: Optional category label.
        creator_id: FK to ``creators.id`` (the publishing account).
        bundle_path: Storage object path of the published bundle (Phase B).
        version: Semantic version string.
        template: Optional builder template id.
        format: On-disk descriptor format (``SKILL.md`` / ``skill.yaml``).
        status: Moderation status (``pending``/``approved``/``flagged``/``removed``).
        install_count: Cached install counter (attribution / trending input).
        id: Server-assigned UUID (absent until inserted).
    """

    slug: str
    name: str
    description: str | None = None
    category: str | None = None
    creator_id: str | None = None
    bundle_path: str | None = None
    version: str = "1.0.0"
    template: str | None = None
    format: str | None = None
    status: str | None = None
    install_count: int = 0
    id: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Skill":
        """Map a Supabase row dict to a ``Skill``, tolerating missing optionals.

        Args:
            row: A ``skills`` (or ``trending_skills`` view) row.

        Returns:
            The typed ``Skill``.
        """
        return cls(
            slug=row.get("slug", ""),
            name=row.get("name", ""),
            description=row.get("description"),
            category=row.get("category"),
            creator_id=row.get("creator_id"),
            bundle_path=row.get("bundle_path"),
            version=row.get("version") or "1.0.0",
            template=row.get("template"),
            format=row.get("format"),
            status=row.get("status"),
            install_count=int(row.get("install_count") or 0),
            id=row.get("id"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (carries ``name`` + ``slug`` for consumers)."""
        return asdict(self)


def _map_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Map a list of skill rows to dicts via ``Skill``, dropping unmappable ones."""
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append(Skill.from_row(row).to_dict())
    return out


def _pack_kali_agent(skill_dir: Path) -> bytes:
    """Pack a skill directory into Phase B ``.kali-agent`` zip bytes.

    Packs into a throwaway temp dir (never AppData) and returns the bytes ready
    for Storage upload. Voice-built skills gain a synthesized ``SKILL.md`` inside
    the zip via :func:`kernel.catalog.package.pack`.

    Args:
        skill_dir: The on-disk skill directory to package.

    Returns:
        The packaged ``.kali-agent`` zip as bytes.
    """
    import tempfile

    from kernel.catalog.package import pack

    with tempfile.TemporaryDirectory(prefix="kali-pack-") as tmp:
        out = pack(skill_dir, Path(tmp) / f"{skill_dir.name}.kali-agent")
        return out.read_bytes()


class CatalogClient(SocialMixin, ModerationMixin):
    """Supabase-backed §4 marketplace catalog client.

    The Supabase client (supabase-py) is constructed lazily and degrades gracefully:
    every method returns an empty/None/"unconfigured" result when Supabase is not
    configured or the library is unavailable — never raising.

    The community social surface (like / rate / comment / get_social, WS-3 Task
    3.4) is provided by :class:`kernel.catalog.social.SocialMixin`, and the
    moderation lifecycle (report / status transitions / queue reads, WS-3 Task
    3.7) by :class:`kernel.catalog.moderation.ModerationMixin` — both split into
    their own modules to keep this file under the size guard while staying
    callable on the one ``catalog_client`` instance the routes hold.
    """

    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL", "")
        self._key = os.environ.get("SUPABASE_KEY", "")
        self._client: Any = None
        self._init_attempted = False
        # Identity layer (3.3): provides the anon device-id and the signed-in
        # account id (auth.uid() == creator_id). Lazily built so tests can swap
        # it; explicit method params still override what it supplies.
        self._identity: CommunityIdentity | None = None

    @property
    def identity(self) -> "CommunityIdentity":
        """The community identity provider (device-id + account session)."""
        if self._identity is None:
            self._identity = CommunityIdentity()
        return self._identity

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
        except Exception as exc:  # noqa: BLE001 — degrade on any init failure
            logger.error("Failed to init Supabase client: %s", exc)

        return self._client

    # ------------------------------------------------------------------ reads

    async def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search approved catalog skills by keyword.

        Args:
            query: Substring matched against ``skills.name``.
            category: Optional ``skills.category`` filter.
            limit: Maximum number of results.

        Returns:
            Mapped skill dicts (``status='approved'`` only), ``[]`` on offline/error.
        """
        client = self._get_client()
        if client is None:
            return []
        try:
            escaped = query.replace("%", "\\%").replace("_", "\\_")
            req = (
                client.table(_SKILLS_TABLE)
                .select(_SKILL_COLUMNS)
                .eq("status", _STATUS_APPROVED)
                .ilike("name", f"%{escaped}%")
                .limit(limit)
            )
            if category:
                req = req.eq("category", category)
            result = req.execute()
            return _map_rows(result.data)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.search failed: %s", exc)
            return []

    async def browse(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List approved skills (optionally by category), newest first.

        Args:
            category: Optional ``skills.category`` filter.
            limit: Maximum number of results.

        Returns:
            Mapped skill dicts, ``[]`` on offline/error.
        """
        client = self._get_client()
        if client is None:
            return []
        try:
            req = (
                client.table(_SKILLS_TABLE)
                .select(_SKILL_COLUMNS)
                .eq("status", _STATUS_APPROVED)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if category:
                req = req.eq("category", category)
            result = req.execute()
            return _map_rows(result.data)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.browse failed: %s", exc)
            return []

    async def trending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return trending skills from the ``trending_skills`` view.

        The view is already restricted to ``status='approved'`` and ordered by a
        derived score (installs + likes + rating, recency-decayed).

        Args:
            limit: Maximum number of results.

        Returns:
            Mapped skill dicts ordered by trending score, ``[]`` on offline/error.
        """
        client = self._get_client()
        if client is None:
            return []
        try:
            result = (
                client.table(_TRENDING_VIEW)
                .select("*")
                .limit(limit)
                .execute()
            )
            return _map_rows(result.data)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.trending failed: %s", exc)
            return []

    async def get_skill(self, slug: str) -> dict[str, Any] | None:
        """Fetch a single approved skill by slug.

        Args:
            slug: Exact ``skills.slug``.

        Returns:
            Mapped skill dict, or None if not found / not approved / offline.
        """
        client = self._get_client()
        if client is None:
            return None
        try:
            result = (
                client.table(_SKILLS_TABLE)
                .select(_SKILL_COLUMNS)
                .eq("slug", slug)
                .eq("status", _STATUS_APPROVED)
                .maybe_single()
                .execute()
            )
            data = result.data if result is not None else None
            if not data:
                return None
            return Skill.from_row(data).to_dict()
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.get_skill failed for %r: %s", slug, exc)
            return None

    # ----------------------------------------------------------------- writes

    async def publish_skill(
        self,
        *,
        slug: str,
        name: str,
        creator_id: str | None = None,
        bundle: bytes | None = None,
        skill_dir: "Path | str | None" = None,
        description: str | None = None,
        category: str | None = None,
        version: str = "1.0.0",
        template: str | None = None,
        skill_format: str = "SKILL.md",
        safety_gate: Callable[..., bool] | None = None,
    ) -> dict[str, Any]:
        """Publish a skill: upload a `.kali-agent` bundle to Storage + insert a row.

        The Phase B catalog format is the ``.kali-agent`` zip. Pass ``skill_dir``
        to pack the on-disk skill directory into one (voice-built skills gain a
        synthesized ``SKILL.md`` inside the zip — see :func:`kernel.catalog.package.pack`);
        the packed bytes are uploaded to the ``skill-bundles`` Storage bucket and
        the row's ``bundle_path`` points at it. ``bundle`` (pre-packed bytes) is
        still accepted for callers that already have a packaged payload — exactly
        one of ``skill_dir`` / ``bundle`` must be given.

        The row is auto-``approved`` only when the ``safety_gate`` predicate
        returns True, else it stays ``status='pending'`` for manual review. When no
        gate is injected the default is the combined §5C
        :func:`kernel.catalog.moderation.auto_approve_gate` — AST scan of any
        bundled ``scripts/*.py`` AND a prose content gate over the SKILL.md body +
        description (so a script-less malicious Markdown skill is NOT auto-approved
        on the AST pass alone). An explicit ``safety_gate`` overrides the default.

        Identity wiring (task 3.3): ``creator_id`` defaults to the signed-in KALI
        account's ``auth.uid()`` (via the identity layer). Publish is account-gated
        — with no explicit ``creator_id`` AND no session it returns ``{"status":
        "sign-in required"}`` rather than silently publishing as anon. An explicit
        ``creator_id`` overrides the session (used by tests).

        Args:
            slug: Stable identity key (also the Storage object name).
            name: Human-readable title.
            creator_id: Publishing creator (``creators.id``); defaults to the
                signed-in account id when omitted.
            bundle: Pre-packaged bundle bytes (mutually exclusive with ``skill_dir``).
            skill_dir: Skill directory to pack into a ``.kali-agent`` zip and upload
                (mutually exclusive with ``bundle``).
            description: Optional description.
            category: Optional category.
            version: Semantic version (defaults ``1.0.0``).
            template: Optional builder template id.
            skill_format: On-disk descriptor format (``SKILL.md``/``skill.yaml``).
            safety_gate: Optional predicate ``(slug, bundle, description) -> bool``;
                True → auto-approve, else pending. Defaults to the combined §5C
                ``auto_approve_gate`` (AST + prose) when omitted.

        Returns:
            The inserted row dict, ``{"status": "sign-in required"}`` when not
            signed in, or ``{"status": "unconfigured"}`` on offline/error.
        """
        if (bundle is None) == (skill_dir is None):
            return {"status": "error", "reason": "exactly one of bundle/skill_dir required"}

        if creator_id is None:
            creator_id = self.identity.current_account_id()
        if creator_id is None:
            return {"status": "sign-in required"}

        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        try:
            if skill_dir is not None:
                bundle = _pack_kali_agent(Path(skill_dir))
            assert bundle is not None  # narrowed by the mutual-exclusion check
            bundle_path = f"{slug}/{slug}.kali-agent"
            client.storage.from_(_BUNDLE_BUCKET).upload(
                bundle_path,
                bundle,
                {"content-type": "application/zip", "upsert": "true"},
            )

            gate = safety_gate if safety_gate is not None else auto_approve_gate
            approved = bool(
                gate(slug=slug, bundle=bundle, description=description)
            )
            row = {
                "slug": slug,
                "name": name,
                "description": description,
                "category": category,
                "creator_id": creator_id,
                "bundle_path": bundle_path,
                "version": version,
                "template": template,
                "format": skill_format,
                "status": _STATUS_APPROVED if approved else _STATUS_PENDING,
            }
            result = client.table(_SKILLS_TABLE).insert(row).execute()
            if result.data:
                return result.data[0]
            return row
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.publish_skill failed for %r: %s", slug, exc)
            return dict(_UNCONFIGURED)

    async def install_skill(
        self,
        slug: str,
        *,
        agents_dir: "Path",
        plugin_registry: Any | None = None,
        skill_executor: Any | None = None,
        agent_runtime: Any | None = None,
    ) -> dict[str, Any]:
        """Install a catalog skill: download its ``.kali-agent`` zip + unpack/install.

        Looks up the approved skill's ``bundle_path``, downloads that object from the
        ``skill-bundles`` Storage bucket, writes it to a temp file, and installs it
        through :func:`kernel.catalog.installer.install_package` — which preserves the
        zip-slip / checksum guards and registers a voice-built (``skill.yaml``) skill
        into the live registry so it is immediately LLM-callable. No AppData writes
        occur here beyond the installer's own atomic deploy into ``agents_dir``.

        Graceful degradation (preserved contract): returns ``{"status":
        "unconfigured"}`` when Supabase is offline and ``{"status": "error", ...}``
        on any download/unpack failure — never raises.

        Args:
            slug: The approved skill's slug to install.
            agents_dir: Directory the skill is installed into.
            plugin_registry: Live ``PluginRegistry`` to register the skill into.
            skill_executor: Optional ``SkillExecutor`` (back-compat deploy path).
            agent_runtime: Optional ``AgentRuntime`` for code-backed agents.

        Returns:
            The installer result dict, or ``{"status": "unconfigured"}`` when offline.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        try:
            skill = await self.get_skill(slug)
            bundle_path = (skill or {}).get("bundle_path")
            if not bundle_path:
                return {"status": "error", "reason": "unknown_skill"}

            data = client.storage.from_(_BUNDLE_BUCKET).download(bundle_path)
            if not data:
                return {"status": "error", "reason": "empty_download"}

            import tempfile

            from kernel.catalog.installer import install_package

            with tempfile.TemporaryDirectory(prefix="kali-install-") as tmp:
                pkg = Path(tmp) / f"{slug}.kali-agent"
                pkg.write_bytes(bytes(data))
                return await install_package(
                    pkg,
                    agents_dir=Path(agents_dir),
                    skill_executor=skill_executor,
                    plugin_registry=plugin_registry,
                    agent_runtime=agent_runtime,
                )
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.install_skill failed for %r: %s", slug, exc)
            return {"status": "error"}

    async def get_creator(self, handle: str) -> dict[str, Any] | None:
        """Fetch a creator profile by handle.

        Args:
            handle: The unique ``creators.handle``.

        Returns:
            Creator row (id, handle, socials), or None if not found / offline.
        """
        client = self._get_client()
        if client is None:
            return None
        try:
            result = (
                client.table(_CREATORS_TABLE)
                .select("id, handle, socials, created_at")
                .eq("handle", handle)
                .maybe_single()
                .execute()
            )
            data = result.data if result is not None else None
            return data or None
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.get_creator failed for %r: %s", handle, exc)
            return None

    async def upsert_creator(
        self,
        *,
        creator_id: str,
        handle: str,
        socials: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create or update a creator profile (handle + self-declared socials).

        ``socials`` are DISPLAY strings only (TikTok/IG/YT/Telegram/site handles) —
        never OAuth tokens or platform credentials (§2/§7 anti-pivot). Identity
        wiring is task 3.3: ``creator_id`` is accepted as a parameter (it equals the
        account's ``auth.users.id``), not derived from an auth session here.

        Args:
            creator_id: The account id (``creators.id`` == ``auth.users.id``).
            handle: The unique public handle.
            socials: Optional self-declared display links.

        Returns:
            The upserted row, or ``{"status": "unconfigured"}`` on offline/error.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        try:
            row = {"id": creator_id, "handle": handle, "socials": socials or {}}
            result = client.table(_CREATORS_TABLE).upsert(row).execute()
            if result.data:
                return result.data[0]
            return row
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.upsert_creator failed for %r: %s", handle, exc)
            return dict(_UNCONFIGURED)

    async def record_install(
        self,
        slug: str,
        device_id: str | None = None,
        creator_attrib: str | None = None,
    ) -> dict[str, Any]:
        """Record an install event + increment the skill's install counter.

        Inserts an ``installs`` row (opaque ``device_id``, no PII; optional
        ``creator_attrib`` for the credited creator) and increments
        ``skills.install_count``. Identity wiring (task 3.3): ``device_id`` defaults
        to the anonymous local device-id (via the identity layer) when omitted; an
        explicit value overrides it (used by tests).

        NOTE (seam): the increment is a read-modify-write (read current count →
        write +1), which is NOT atomic under concurrency. The production-correct
        path is a Postgres ``rpc`` (atomic ``install_count = install_count + 1``) or
        a DB trigger on ``installs`` — deferred to the live-Supabase wiring. Here it
        is RMW so it is exercisable against the mock without a live function.

        Args:
            slug: The installed skill's slug.
            device_id: Opaque anonymous device id (no PII); defaults to the local
                device-id when omitted.
            creator_attrib: Optional creator credited for this install.

        Returns:
            ``{"status": "ok", "install_count": N}`` on success, or
            ``{"status": "unconfigured"}`` / ``{"status": "error"}`` otherwise.
        """
        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        if device_id is None:
            device_id = self.identity.get_device_id()
        try:
            lookup = (
                client.table(_SKILLS_TABLE)
                .select("id, install_count")
                .eq("slug", slug)
                .maybe_single()
                .execute()
            )
            skill = lookup.data if lookup is not None else None
            if not skill:
                logger.warning("record_install: unknown slug %r", slug)
                return {"status": "error", "reason": "unknown_skill"}

            skill_id = skill["id"]
            new_count = int(skill.get("install_count") or 0) + 1

            client.table(_INSTALLS_TABLE).insert(
                {
                    "skill_id": skill_id,
                    "device_id": device_id,
                    "creator_attrib": creator_attrib,
                }
            ).execute()

            client.table(_SKILLS_TABLE).update(
                {"install_count": new_count}
            ).eq("id", skill_id).execute()

            return {"status": "ok", "install_count": new_count}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("catalog.record_install failed for %r: %s", slug, exc)
            return {"status": "error"}

    # ------------------------------------------------------------- local read

    async def local_search(
        self,
        query: str,
        agents_dir: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Search locally installed agents/skills by name/description.

        Preserved from the prototype — the «Сообщество» backend (kernel/main.py)
        merges local results with the cloud catalog and degrades to local-only when
        Supabase is offline.

        Args:
            query: Search string (empty returns all installed).
            agents_dir: Path to the agents directory. Defaults to ``agents/``.

        Returns:
            List of matching local package dicts with ``installed=True``.
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

                with open(manifest_path, encoding="utf-8") as fh:
                    manifest = yaml.safe_load(fh)
                name: str = manifest.get("name", "")
                desc: str = manifest.get("description", "")
                if (
                    query_lower
                    and query_lower not in name.lower()
                    and query_lower not in desc.lower()
                ):
                    continue
                results.append(
                    {
                        "name": name,
                        "description": desc,
                        "type": "skill"
                        if (agent_dir / "skill.yaml").exists()
                        else "agent",
                        "category": "local",
                        "downloads": 0,
                        "rating_avg": 0,
                        "trust_level": "official",
                        "version": manifest.get("version", "1.0.0"),
                        "installed": True,
                    }
                )
            except Exception:  # noqa: BLE001 — skip an unreadable manifest
                continue
        return results
