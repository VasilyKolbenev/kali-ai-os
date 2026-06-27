"""Community moderation lifecycle — combined auto-approve gate + admin transitions.

WS-3 Task 3.7 (§5C of the marketplace design spec). Split out of
``kernel/catalog/client.py`` (which would otherwise exceed the 800-line guard) as
a MIXIN that ``CatalogClient`` inherits, so the methods stay callable as
``catalog_client.report(...)`` while the file stays lean.

Two responsibilities:

1. **Auto-approve gate** (``auto_approve_gate``) — the predicate wired into
   ``publish_skill``'s ``safety_gate`` seam. A skill auto-``approved`` ONLY IF the
   AST scan of any bundled ``scripts/*.py`` passes AND the prose gate
   (``content_gate.scan_prose``) passes. With no scripts the AST half is trivially
   satisfied, so the **prose gate is the load-bearing check** — exactly the §5C
   point: a script-less, pure-Markdown skill must still clear a content review
   before it is auto-approved; otherwise it goes to ``pending`` for a human.

2. **Status machine** (``report`` / ``set_skill_status`` / ``set_comment_status`` /
   ``list_pending`` / ``list_flags``) — the moderation queue operations.

   * ``report`` is PUBLIC (the report button): anon or signed-in, it inserts a
     ``flags`` row. RLS allows the INSERT for everyone.
   * ``set_skill_status`` / ``set_comment_status`` / ``list_pending`` /
     ``list_flags`` are **SERVICE-ROLE / ADMIN-ONLY**. In production they run with
     the Supabase ``service_role`` key (which bypasses RLS) from a privileged
     backend — NEVER the public anon client. The public RLS policies deliberately
     grant no SELECT on ``flags`` and no status-transition path on
     ``skills``/``comments`` to anon/authenticated, so these are inert from the
     public client by design; the routes that expose them are gated behind a
     moderator check (``kernel/main.py``), and real moderation auth is a
     human-gate (Vasily reviews at MVP). Here they are mock-tested.

Graceful degradation (same contract as the rest of CatalogClient): an
unconfigured / offline Supabase yields ``[]`` / ``{"status": "unconfigured"}`` and
never raises.
"""

from __future__ import annotations

import io
import logging
import tarfile
from typing import Any

from kernel.catalog.content_gate import scan_prose

logger = logging.getLogger(__name__)

# §4 moderation table names (single source of truth for the mapping).
_SKILLS_TABLE = "skills"
_COMMENTS_TABLE = "comments"
_FLAGS_TABLE = "flags"

_UNCONFIGURED: dict[str, str] = {"status": "unconfigured"}

# §4 status enums (skills + comments share the same lifecycle values).
_SKILL_STATUSES: frozenset[str] = frozenset(
    {"pending", "approved", "flagged", "removed"}
)
_COMMENT_STATUSES: frozenset[str] = frozenset(
    {"pending", "approved", "flagged", "removed"}
)

# §4 flags.target_type enum.
_FLAG_TARGETS: frozenset[str] = frozenset({"skill", "comment"})

# Columns selected for a pending skill (moderation queue read).
_PENDING_SKILL_COLUMNS = (
    "id, slug, name, description, category, creator_id, bundle_path, "
    "version, template, format, status, install_count, created_at, updated_at"
)
# Columns selected for a flag (moderation queue read).
_FLAG_COLUMNS = "id, target_type, target_id, reason, reporter_id, created_at"


def _extract_bundle_prose_and_scripts(
    bundle: bytes,
) -> tuple[str, list[str], bool]:
    """Pull a published bundle's SKILL.md body + scripts/*.py source out of bytes.

    The publisher packages a skill as a ``.tar.gz`` with a single top-level
    ``<name>/`` arcname holding ``SKILL.md`` and an optional ``scripts/`` tree
    (see ``kernel/skills/publisher._add_bundle_members``). The auto-approve gate
    needs the SKILL.md prose (for the content gate) and every Python script (for
    the AST gate), so this reads them back out of the in-memory bundle.

    A bundle that is not a readable tar.gz (e.g. a raw/placeholder blob) yields
    ``("", [], False)`` — the ``False`` tells the gate the bundle was
    un-inspectable, so it fails CLOSED (no auto-approve) rather than waving
    through content it could not read.

    Args:
        bundle: The packaged bundle bytes.

    Returns:
        ``(prose, scripts, readable)`` — ``prose`` is the concatenated text of
        every ``SKILL.md`` found; ``scripts`` is the decoded source of every
        ``scripts/**/*.py`` member; ``readable`` is True iff the bundle parsed as
        a tar archive.
    """
    prose_parts: list[str] = []
    scripts: list[str] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                base = name.rsplit("/", 1)[-1]
                is_script = "/scripts/" in name or name.startswith("scripts/")
                if base == "SKILL.md" or (is_script and base.endswith(".py")):
                    fh = tar.extractfile(member)
                    if fh is None:
                        continue
                    try:
                        text = fh.read().decode("utf-8", errors="replace")
                    finally:
                        fh.close()
                    if base == "SKILL.md":
                        prose_parts.append(text)
                    else:
                        scripts.append(text)
    except (tarfile.TarError, OSError, EOFError) as exc:
        logger.debug("auto_approve_gate: bundle not a readable tar (%s)", exc)
        return "", [], False
    return "\n".join(prose_parts), scripts, True


def auto_approve_gate(
    *,
    slug: str,
    bundle: bytes,
    description: str | None = None,
) -> bool:
    """Decide whether a freshly published skill may auto-``approve``.

    The combined §5C gate. Returns True (auto-approve) ONLY when ALL hold:

    * **Bundle is inspectable** — it parses as a tar archive; an un-readable /
      placeholder bundle fails closed (→ pending), never auto-approved sight
      unseen.
    * **AST scan** — every ``scripts/*.py`` in the bundle passes
      ``kernel.builder.safety_gate.check_code``. No scripts ⇒ trivially passes.
    * **Prose gate** — the SKILL.md body (plus the publish ``description``) passes
      ``content_gate.scan_prose`` (no prompt-injection / social-engineering
      heuristic match).

    Anything else returns False, so ``publish_skill`` leaves the row ``pending``
    for manual review. Because a script-less skill clears the AST half for free,
    the prose gate is the load-bearing check — a malicious Markdown-only skill is
    NOT auto-approved. The decision is conservative by construction (any single
    failing signal blocks auto-approve); the human review is the real backstop.

    Args:
        slug: The skill's slug (for logging context).
        bundle: The packaged bundle bytes (tar.gz: SKILL.md + optional scripts).
        description: The publish-time description, scanned alongside the body.

    Returns:
        True to auto-approve, False to route to ``pending`` for manual review.
    """
    prose, scripts, readable = _extract_bundle_prose_and_scripts(bundle)
    if not readable:
        logger.info(
            "auto_approve_gate[%s]: bundle not inspectable → pending (fail-closed)",
            slug,
        )
        return False

    # AST half — every script must pass; a single failure blocks auto-approve.
    if scripts:
        try:
            from kernel.builder.safety_gate import check_code
        except ImportError:
            logger.warning(
                "auto_approve_gate[%s]: safety_gate unavailable — not auto-approving",
                slug,
            )
            return False
        for source in scripts:
            result = check_code(source)
            if not result.safe:
                logger.info(
                    "auto_approve_gate[%s]: AST scan flagged scripts → pending: %s",
                    slug,
                    result.issues,
                )
                return False

    # Prose half — the load-bearing §5C check for script-less skills.
    combined_prose = "\n".join(p for p in (prose, description) if p)
    ok, issues = scan_prose(combined_prose)
    if not ok:
        logger.info(
            "auto_approve_gate[%s]: prose gate flagged content → pending: %s",
            slug,
            issues,
        )
        return False

    return True


class ModerationMixin:
    """Report + admin status-transition methods mixed into ``CatalogClient``.

    ``report`` is public (the report button). ``set_skill_status`` /
    ``set_comment_status`` / ``list_pending`` / ``list_flags`` are
    **service-role / admin-only** — in production they require the Supabase
    ``service_role`` key (RLS-bypassing) and must NEVER be reachable from the
    public client; the FastAPI routes gate them behind a moderator check and the
    real authority is a human (Vasily at MVP). All methods preserve the
    graceful-degradation contract.
    """

    # -------------------------------------------------------------- public: report

    async def report(
        self: Any,
        target_type: str,
        target_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """File a moderation flag against a skill or comment (PUBLIC report button).

        Inserts a ``flags`` row. Open to everyone (anon or signed-in) — the RLS
        INSERT policy allows it. The reporter is attributed to the signed-in
        account when there is one, else left null (an anonymous report; the
        anonymous device-id is NOT written to ``reporter_id``, which is an
        ``auth.users`` FK). ``target_id`` is the skill/comment UUID.

        Args:
            target_type: ``"skill"`` or ``"comment"``.
            target_id: The UUID of the reported skill/comment.
            reason: Optional free-text reason from the reporter.

        Returns:
            ``{"status": "ok"}`` on a successful insert, ``{"status": "invalid"}``
            for a bad ``target_type``, or ``{"status": "unconfigured"}`` /
            ``{"status": "error"}`` on offline/failure.
        """
        if target_type not in _FLAG_TARGETS:
            return {"status": "invalid", "reason": "bad_target_type"}

        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        reporter_id = self.identity.current_account_id()
        try:
            client.table(_FLAGS_TABLE).insert(
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "reason": reason,
                    "reporter_id": reporter_id,
                }
            ).execute()
            return {"status": "ok"}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("moderation.report failed for %s/%s: %s", target_type, target_id, exc)
            return {"status": "error"}

    # ------------------------------------------------ admin: status transitions

    async def set_skill_status(self: Any, slug: str, status: str) -> dict[str, Any]:
        """Transition a skill's moderation status (SERVICE-ROLE / ADMIN-ONLY).

        Moves ``skills.status`` to one of ``pending``/``approved``/``flagged``/
        ``removed``. In production this MUST run with the Supabase ``service_role``
        key — the public RLS policies grant no such transition to anon/authenticated
        (a creator's own UPDATE only re-asserts ownership, never lifts status), so
        this is a privileged operation gated behind the moderator route. Never call
        it from the public client.

        Args:
            slug: The target skill's slug.
            status: New status (``pending``/``approved``/``flagged``/``removed``).

        Returns:
            ``{"status": "ok", "skill_status": status}`` on success,
            ``{"status": "invalid"}`` for a bad status, ``{"status": "error"}``
            for an unknown slug / failure, or ``{"status": "unconfigured"}``
            offline.
        """
        if status not in _SKILL_STATUSES:
            return {"status": "invalid", "reason": "bad_status"}

        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        try:
            result = (
                client.table(_SKILLS_TABLE)
                .update({"status": status})
                .eq("slug", slug)
                .execute()
            )
            if not getattr(result, "data", None):
                return {"status": "error", "reason": "unknown_skill"}
            return {"status": "ok", "skill_status": status}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("moderation.set_skill_status failed for %r: %s", slug, exc)
            return {"status": "error"}

    async def set_comment_status(self: Any, comment_id: str, status: str) -> dict[str, Any]:
        """Transition a comment's moderation status (SERVICE-ROLE / ADMIN-ONLY).

        Moves ``comments.status`` to one of ``pending``/``approved``/``flagged``/
        ``removed``. Service-role-only for the same reason as
        ``set_skill_status``: an author's own UPDATE cannot self-approve (RLS WITH
        CHECK only re-asserts ownership; the public SELECT still gates on
        ``approved``). Gated behind the moderator route; never call from the
        public client.

        Args:
            comment_id: The target comment's UUID.
            status: New status (``pending``/``approved``/``flagged``/``removed``).

        Returns:
            ``{"status": "ok", "comment_status": status}`` on success,
            ``{"status": "invalid"}`` for a bad status, ``{"status": "error"}``
            for an unknown id / failure, or ``{"status": "unconfigured"}``
            offline.
        """
        if status not in _COMMENT_STATUSES:
            return {"status": "invalid", "reason": "bad_status"}

        client = self._get_client()
        if client is None:
            return dict(_UNCONFIGURED)
        try:
            result = (
                client.table(_COMMENTS_TABLE)
                .update({"status": status})
                .eq("id", comment_id)
                .execute()
            )
            if not getattr(result, "data", None):
                return {"status": "error", "reason": "unknown_comment"}
            return {"status": "ok", "comment_status": status}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("moderation.set_comment_status failed for %r: %s", comment_id, exc)
            return {"status": "error"}

    # ----------------------------------------------------- admin: queue reads

    async def list_pending(self: Any, limit: int = 100) -> list[dict[str, Any]]:
        """List skills awaiting manual review (SERVICE-ROLE / ADMIN-ONLY).

        Returns ``skills`` rows with ``status='pending'`` (the manual-review
        queue), newest first. Service-role-only: the public SELECT policy exposes
        only ``approved`` skills, so a ``pending`` queue is invisible to the
        anon/authenticated client by design. Gated behind the moderator route.

        Args:
            limit: Maximum number of rows.

        Returns:
            Pending ``skills`` rows, or ``[]`` on offline/error.
        """
        client = self._get_client()
        if client is None:
            return []
        try:
            result = (
                client.table(_SKILLS_TABLE)
                .select(_PENDING_SKILL_COLUMNS)
                .eq("status", "pending")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            rows = getattr(result, "data", None)
            return [r for r in (rows or []) if isinstance(r, dict)]
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("moderation.list_pending failed: %s", exc)
            return []

    async def list_flags(self: Any, limit: int = 100) -> list[dict[str, Any]]:
        """List the moderation report queue (SERVICE-ROLE / ADMIN-ONLY).

        Returns ``flags`` rows newest first. Service-role-only: ``flags`` has NO
        public SELECT policy (a reporter cannot even read back their own report),
        so this is empty from the anon/authenticated client by design and only the
        service_role can work the queue. Gated behind the moderator route.

        Args:
            limit: Maximum number of rows.

        Returns:
            Flag rows, or ``[]`` on offline/error.
        """
        client = self._get_client()
        if client is None:
            return []
        try:
            result = (
                client.table(_FLAGS_TABLE)
                .select(_FLAG_COLUMNS)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            rows = getattr(result, "data", None)
            return [r for r in (rows or []) if isinstance(r, dict)]
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("moderation.list_flags failed: %s", exc)
            return []
