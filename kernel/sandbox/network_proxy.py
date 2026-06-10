"""Network proxy — handles 'network.request' JSON-RPC from agents."""

import asyncio
import ipaddress
import json as json_mod
import logging
import re
import socket
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from kernel.sandbox.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _resolves_to_private(host: str) -> bool:
    """Return True if ``host`` resolves to a loopback/link-local/private address.

    Blocks SSRF to internal infrastructure (127.0.0.0/8, 169.254.0.0/16,
    10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1, etc.). An unresolvable
    host is treated as private (fail closed).

    Args:
        host: Hostname or IP literal to evaluate.

    Returns:
        True if any resolved address is private/loopback/link-local.
    """
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return True
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the domain whitelist + private-IP checks on every 30x redirect.

    urllib follows redirects transparently, so an allowed URL could be redirected
    to an arbitrary host (SSRF). This handler validates each redirect target
    before urllib follows it.
    """

    def __init__(self, is_allowed: Callable[[str], bool]) -> None:
        self._is_allowed = is_allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        host = (urlparse(newurl).hostname or "").lower()
        if not self._is_allowed(host):
            raise ValueError(f"Redirect to non-whitelisted host '{host}' blocked")
        if _resolves_to_private(host):
            raise ValueError(f"Redirect to private/loopback host '{host}' blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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

        if _resolves_to_private(domain):
            logger.warning(
                "Agent '%s' blocked from private/loopback host '%s'", agent_name, domain
            )
            return {"error": f"Blocked: {domain} resolves to a private address"}

        if not self._rate_limiter.check(agent_name):
            return {"error": "Rate limit exceeded"}

        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        json_body = params.get("json")
        timeout = min(int(params.get("timeout", 30)), 30)

        def _allowed(host: str) -> bool:
            return self.is_domain_allowed(agent_name, host)

        try:
            return await asyncio.to_thread(
                self._sync_request, url, method, headers, json_body, timeout, _allowed
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
        is_allowed: Callable[[str], bool],
    ) -> dict[str, Any]:
        """Perform the blocking HTTP request synchronously.

        Args:
            url: Target URL.
            method: HTTP method (GET, POST, etc.).
            headers: Request headers dict.
            json_body: Optional JSON-serialisable body.
            timeout: Request timeout in seconds.
            is_allowed: Predicate re-applied to every redirect target host.

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
        opener = urllib.request.build_opener(_ValidatingRedirectHandler(is_allowed))
        with opener.open(req, data=data, timeout=timeout) as resp:
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
