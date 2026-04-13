"""Logger skill template — record timestamped events with notes."""

import logging
from datetime import datetime
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)

_MAX_HISTORY = 100


class LoggerTemplate(SkillTemplate):
    """Record arbitrary events with optional notes and support search.

    Entries are stored in ``entries.json`` as a list ordered by insertion time.

    Config keys:
        (none required)
    """

    @property
    def template_name(self) -> str:
        return "logger"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch logger actions.

        Args:
            action: One of "log", "search", "history".
            args: Action-specific arguments.
            config: Skill configuration (currently unused).

        Returns:
            Result dict appropriate for the action.
        """
        if action == "log":
            return await self._log(args)
        if action == "search":
            return await self._search(args)
        if action == "history":
            return await self._history(args)
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _log(self, args: dict[str, Any]) -> dict[str, Any]:
        """Record a timestamped event with an optional note.

        Args:
            args: Must contain ``event`` (str). Optionally ``note`` (str).

        Returns:
            Dict with the recorded entry including ``timestamp``.
        """
        event: str = str(args.get("event", ""))
        note: str = str(args.get("note", ""))
        now_str = datetime.now().isoformat()

        entry: dict[str, Any] = {"timestamp": now_str, "event": event, "note": note}

        entries: list[dict[str, Any]] = await self.load_data("entries.json", default=[])
        entries.append(entry)
        if len(entries) > _MAX_HISTORY:
            entries = entries[-_MAX_HISTORY:]
        await self.save_data("entries.json", entries)

        logger.debug("Logger '%s': logged event %r", self.skill_name, event)
        return entry

    async def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search recorded entries by substring match in event or note.

        Args:
            args: Must contain ``query`` (str).

        Returns:
            Dict with ``results`` list of matching entries and ``count``.
        """
        query: str = str(args.get("query", "")).lower()
        entries: list[dict[str, Any]] = await self.load_data("entries.json", default=[])
        results = [
            e for e in entries
            if query in e.get("event", "").lower() or query in e.get("note", "").lower()
        ]
        return {"results": results, "count": len(results)}

    async def _history(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return the latest N entries.

        Args:
            args: Optionally contains ``count`` (int, default 20).

        Returns:
            Dict with ``entries`` list (newest last, up to ``count`` items).
        """
        count: int = int(args.get("count", 20))
        entries: list[dict[str, Any]] = await self.load_data("entries.json", default=[])
        return {"entries": entries[-count:], "total": len(entries)}
