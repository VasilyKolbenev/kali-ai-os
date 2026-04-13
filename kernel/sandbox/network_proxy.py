"""Network proxy — handles 'network.request' JSON-RPC from agents."""

import asyncio
import json as json_mod
import logging
import re
import urllib.request
from typing import Any
from urllib.parse import urlparse

from kernel.sandbox.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class NetworkProxy:
    """Proxies HTTP requests for sandboxed agents.

    Enforces per-agent domain whitelists and request rate limits before
    forwarding outbound HTTP calls made by agents.
    """

    def __init__(self, max_requests_per_min: int = 60) -> None:
        """Initialise the proxy.

        Args:
            max_requests_per_min: Rate limit applied per agent per minute.
        """
        self._allowed_domains: dict[str, list[str]] = {}
        self._rate_limiter = RateLimiter(max_requests=max_requests_per_min, window_seconds=60.0)

    def set_allowed_domains(self, agent_name: str, domains: list[str]) -> None:
        """Register the domain whitelist for an agent.

        Args:
            agent_name: Unique agent identifier.
            domains: List of allowed domain patterns (supports leading wildcard).
        """
        self._allowed_domains[agent_name] = [d.lower() for d in domains]

    def is_domain_allowed(self, agent_name: str, domain: str) -> bool:
        """Check whether a domain is whitelisted for the given agent.

        Args:
            agent_name: Unique agent identifier.
            domain: Hostname to check (without scheme or path).

        Returns:
            True if the domain matches at least one whitelist pattern.
        """
        patterns = self._allowed_domains.get(agent_name, [])
        domain = domain.lower()
        return any(self._match(domain, p) for p in patterns)

    async def handle(self, agent_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle a network.request RPC call from an agent.

        Args:
            agent_name: Unique agent identifier making the request.
            params: RPC parameters — url, method, headers, json, timeout.

        Returns:
            Dict with 'status' and 'body' on success, or 'error' on failure.
        """
        url = params.get("url", "").strip()
        if not url:
            return {"error": "URL is required"}

        domain = self._extract_domain(url)
        if not self.is_domain_allowed(agent_name, domain):
            logger.warning("Agent '%s' blocked from domain '%s'", agent_name, domain)
            return {"error": f"Blocked: {domain} not in whitelist"}

        if not self._rate_limiter.check(agent_name):
            return {"error": "Rate limit exceeded"}

        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        json_body = params.get("json")
        timeout = min(int(params.get("timeout", 30)), 30)

        try:
            return await asyncio.to_thread(
                self._sync_request, url, method, headers, json_body, timeout
            )
        except Exception as exc:
            logger.error(
                "NetworkProxy request failed for agent '%s' url='%s': %s",
                agent_name,
                url,
                exc,
            )
            return {"error": str(exc)}

    def _sync_request(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        json_body: Any,
        timeout: int,
    ) -> dict[str, Any]:
        """Perform the blocking HTTP request synchronously.

        Args:
            url: Target URL.
            method: HTTP method (GET, POST, etc.).
            headers: Request headers dict.
            json_body: Optional JSON-serialisable body.
            timeout: Request timeout in seconds.

        Returns:
            Dict with 'status' and 'body', or 'error' on failure.
        """
        req = urllib.request.Request(url, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        data: bytes | None = None
        if json_body is not None:
            data = json_mod.dumps(json_body).encode()
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            return {"status": resp.status, "body": body}

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Parse the hostname from a URL string.

        Args:
            url: Full URL to parse.

        Returns:
            Lowercase hostname, or empty string on failure.
        """
        try:
            return (urlparse(url).hostname or "").lower()
        except Exception:
            return ""

    @staticmethod
    def _match(domain: str, pattern: str) -> bool:
        """Match a domain against a glob-style pattern supporting leading wildcards.

        Args:
            domain: Lowercase hostname to test.
            pattern: Pattern string; '*' matches any sequence of domain chars.

        Returns:
            True if the domain matches the pattern.
        """
        regex = re.escape(pattern).replace(r"\*", "[a-z0-9.-]*")
        return bool(re.fullmatch(regex, domain))
