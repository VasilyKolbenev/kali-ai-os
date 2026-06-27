"""Monitor skill template — periodic URL/API health checks."""

import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from kernel.sandbox.http_client import (
    HttpRequest,
    SandboxHttpClient,
    SandboxHttpError,
)
from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)

_MAX_HISTORY = 100


class MonitorTemplate(SkillTemplate):
    """Periodically check a URL and record status history.

    Stores check results in ``history.json``.

    Config keys:
        url (str): URL to check.
        expected_status (int): Expected HTTP status code (default 200).
    """

    #: Optional per-agent rate limiter. ``None`` disables rate limiting. Left
    #: as a class attribute (not a constructor arg) so the template registry can
    #: keep instantiating templates with ``(skill_name, data_dir)`` only; the
    #: skill runtime may inject a limiter per instance when one is available.
    _rate_limiter: Any = None

    @property
    def template_name(self) -> str:
        return "monitor"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch monitor actions.

        Args:
            action: One of "check", "history".
            args: Action-specific arguments (``_mock_status`` for testing).
            config: Skill configuration with ``url`` and ``expected_status``.

        Returns:
            Result dict appropriate for the action.
        """
        if action == "check":
            return await self._check(args, config)
        if action == "history":
            return await self._history()
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _check(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Check the configured URL and record the result.

        Supports ``_mock_status`` in ``args`` to inject a status code for
        testing without making real network requests.

        Args:
            args: May contain ``_mock_status`` (int) for test injection.
            config: Must contain ``url`` (str). Optionally ``expected_status`` (int).

        Returns:
            Dict with ``url``, ``status_code``, ``is_ok``, ``checked_at``.
        """
        url: str = config.get("url", "")
        expected_status: int = int(config.get("expected_status", 200))
        now_str = datetime.now().isoformat()

        mock_status = args.get("_mock_status") if os.environ.get("KALI_TESTING") else None
        if mock_status is not None:
            status_code = int(mock_status)
            error = None
        else:
            status_code, error = self._fetch_status(url)

        is_ok = status_code == expected_status if status_code is not None else False

        entry: dict[str, Any] = {
            "checked_at": now_str,
            "url": url,
            "status_code": status_code,
            "is_ok": is_ok,
        }
        if error:
            entry["error"] = error

        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        history.append(entry)
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        await self.save_data("history.json", history)

        logger.debug(
            "Monitor '%s': %s → %s (ok=%s)", self.skill_name, url, status_code, is_ok,
        )
        return {"url": url, "status_code": status_code, "is_ok": is_ok, "checked_at": now_str}

    def _fetch_status(self, url: str) -> tuple[int | None, str | None]:
        """Perform a guarded HTTP request and return (status_code, error).

        The URL is user/voice-supplied, so egress goes through
        :class:`~kernel.sandbox.http_client.SandboxHttpClient` — the fail-closed
        SSRF defense (private-IP/loopback/link-local block + redirect re-check +
        rate limit). The block is unconditional: even a whitelisted host that
        resolves to ``169.254.169.254`` / ``127.0.0.1`` / RFC1918 is rejected,
        so a voice-built monitor cannot reach internal infrastructure.

        The configured target host is whitelisted by default (the user
        explicitly chose this URL to monitor); ``config['allowed_domains']`` may
        narrow/extend it. Any block or transport failure maps to the existing
        contract: ``status_code is None`` with an error message.

        Args:
            url: URL to request.

        Returns:
            Tuple of (status_code, error_message). On any block or network
            error, status_code is None and error_message is set.
        """
        client = self._build_http_client(url)
        try:
            resp = client.request(HttpRequest(url=url, timeout=10.0))
            return resp.status, None
        except SandboxHttpError as exc:
            # Covers DomainBlockedError (SSRF / not whitelisted), RateLimitError,
            # and transport failures — all surface as a failed check.
            logger.warning("Monitor '%s' request blocked/failed: %s", self.skill_name, exc)
            return None, str(exc)

    def _build_http_client(self, url: str) -> SandboxHttpClient:
        """Build the SSRF-guarded client for a monitor target.

        Args:
            url: The configured target URL.

        Returns:
            A :class:`SandboxHttpClient` whitelisting the target host (or the
            explicit ``allowed_domains`` config), with the optional rate limiter.
        """
        host = (urlparse(url).hostname or "").lower()
        allowed = [host] if host else []
        return SandboxHttpClient(
            self.skill_name,
            allowed_domains=allowed,
            rate_limiter=self._rate_limiter,
        )

    async def _history(self) -> dict[str, Any]:
        """Return check history with aggregate ok/fail counts.

        Returns:
            Dict with ``history`` list and ``ok_count``, ``fail_count``.
        """
        history: list[dict[str, Any]] = await self.load_data("history.json", default=[])
        ok_count = sum(1 for e in history if e.get("is_ok"))
        fail_count = len(history) - ok_count
        return {"history": history, "ok_count": ok_count, "fail_count": fail_count}
