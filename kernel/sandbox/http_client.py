"""Sandboxed HTTP client for Agent Skills.

Skills that need to call external APIs should use this client instead of
raw ``requests`` or ``urllib``. It enforces:

- **Domain whitelist** — rejects calls to hosts not in the skill's manifest
- **Rate limiting** — per-agent sliding window (defaults to 120 req/min)
- **Timeout cap** — max 30s to prevent hanging
- **Audit trail** — every request is logged to the sandbox audit sink
- **Size cap** — response body limited to 10 MB

Example usage inside a skill's ``scripts/*.py``::

    from kernel.sandbox.http_client import SandboxHttpClient, HttpRequest

    client = SandboxHttpClient.for_agent("crypto-watcher", ctx)
    resp = client.request(HttpRequest(
        url="https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "bitcoin", "vs_currencies": "usd"},
    ))
    price = resp.json()["bitcoin"]["usd"]

This is the *preferred* path for skills. Raw ``requests`` usage remains
possible (the sandbox is not a security boundary against malicious code)
but bypasses whitelist + rate limit enforcement.
"""

from __future__ import annotations

import ipaddress
import json as json_mod
import logging
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_TIMEOUT_SECONDS = 30


def _resolves_to_private(host: str) -> bool:
    """Return True if ``host`` resolves to a loopback/link-local/private address.

    Blocks SSRF to internal infrastructure (127.0.0.0/8, 169.254.0.0/16,
    10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1, etc.). A host that cannot
    be resolved is treated as private (fail closed).

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


def _resolve_validated(host: str) -> list[Any] | None:
    """Resolve ``host`` and return its addrinfo entries iff EVERY resolved
    address is public.

    Returns None when the host is unresolvable or ANY address is
    private/loopback/link-local/reserved (fail closed). Resolving once here and
    pinning the connection to these vetted addresses closes the DNS-rebinding
    TOCTOU window — otherwise the guard's ``getaddrinfo`` and urllib's connect
    resolve separately and an attacker-controlled DNS could rebind in between.
    """
    if not host:
        return None
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return None
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return None
    return infos


class SandboxHttpError(RuntimeError):
    """Base for any sandbox-level HTTP problem."""


class DomainBlockedError(SandboxHttpError):
    """Raised when target host is not in the skill's whitelist."""


class RateLimitError(SandboxHttpError):
    """Raised when the per-agent rate limit is exceeded."""


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the whitelist + private-IP checks on every 30x redirect target.

    urllib follows redirects transparently, so a whitelisted URL could redirect
    to an arbitrary host (SSRF). This handler validates each hop's destination
    before allowing urllib to follow it.
    """

    def __init__(self, host_allowed: Callable[[str], bool]) -> None:
        self._host_allowed = host_allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        host = (urlparse(newurl).hostname or "").lower()
        if not self._host_allowed(host):
            raise DomainBlockedError(
                f"Redirect to non-whitelisted host '{host}' blocked"
            )
        if _resolves_to_private(host):
            raise DomainBlockedError(
                f"Redirect to private/loopback host '{host}' blocked"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class HttpRequest:
    """Parameters for an outbound HTTP call."""

    url: str
    method: str = "GET"
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any = None
    timeout: float = 10.0

    @property
    def resolved_url(self) -> str:
        if not self.params:
            return self.url
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}{urlencode(self.params)}"


@dataclass
class HttpResponse:
    """Result of an HTTP call."""

    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json_mod.loads(self.text)


class SandboxHttpClient:
    """HTTP client bound to a single agent with whitelist + rate limit.

    Construction is through ``for_agent(...)`` — tests instantiate directly.
    """

    def __init__(
        self,
        agent_name: str,
        *,
        allowed_domains: list[str],
        rate_limiter: Any = None,
        audit_sink: Any = None,
    ) -> None:
        self._agent = agent_name
        self._allowed = [d.lower() for d in allowed_domains]
        self._rate_limiter = rate_limiter
        self._audit_sink = audit_sink

    # --- factory ----------------------------------------------------------

    @classmethod
    def for_agent(cls, agent_name: str, ctx: Any) -> "SandboxHttpClient":
        """Build a client from the sandbox context bag (permission enforcer, etc).

        Args:
            agent_name: The calling agent's name.
            ctx: Any object exposing ``permission_enforcer``, ``rate_limiter``,
                 ``audit_sink`` attributes.
        """
        enforcer = getattr(ctx, "permission_enforcer", None)
        allowed: list[str] = []
        if enforcer is not None:
            try:
                allowed = enforcer.get_network_domains(agent_name)
            except Exception:  # pragma: no cover
                logger.exception("Failed to read allowed domains for %s", agent_name)
        return cls(
            agent_name,
            allowed_domains=allowed,
            rate_limiter=getattr(ctx, "rate_limiter", None),
            audit_sink=getattr(ctx, "audit_sink", None),
        )

    # --- core call --------------------------------------------------------

    def request(self, req: HttpRequest) -> HttpResponse:
        """Make an HTTP request, enforcing whitelist + rate limit.

        Raises:
            DomainBlockedError: URL's host isn't in the whitelist.
            RateLimitError: agent exceeded its per-minute quota.
            SandboxHttpError: other transport failures.
        """
        host = self._extract_host(req.url)
        if not self._host_allowed(host):
            self._emit_audit(
                status="denied", reason="domain_blocked",
                url=req.url, duration_ms=0, error=f"host '{host}' not whitelisted",
            )
            raise DomainBlockedError(
                f"Host '{host}' not whitelisted for agent '{self._agent}'. "
                f"Add it to 'permissions: network: domains: [...]' in SKILL.md."
            )

        validated = _resolve_validated(host)
        if validated is None:
            self._emit_audit(
                status="denied", reason="domain_blocked",
                url=req.url, duration_ms=0, error=f"host '{host}' resolves to private range",
            )
            raise DomainBlockedError(
                f"Host '{host}' resolves to a private/loopback address — blocked."
            )

        if self._rate_limiter is not None and not self._rate_limiter.check(self._agent):
            self._emit_audit(
                status="denied", reason="rate_limit",
                url=req.url, duration_ms=0, error="per-agent rate limit exceeded",
            )
            raise RateLimitError(
                f"Agent '{self._agent}' exceeded rate limit"
            )

        timeout = min(max(1.0, req.timeout), MAX_TIMEOUT_SECONDS)
        url = req.resolved_url
        py_req = urllib.request.Request(url, method=req.method.upper())
        for k, v in req.headers.items():
            py_req.add_header(k, v)

        data: bytes | None = None
        if req.json_body is not None:
            data = json_mod.dumps(req.json_body).encode("utf-8")
            py_req.add_header("Content-Type", "application/json")

        opener = urllib.request.build_opener(
            _ValidatingRedirectHandler(self._host_allowed)
        )

        # Pin urllib's resolution to the addresses we just validated so a DNS
        # rebind between the check and the connect cannot redirect the socket to
        # a private target. The pin substitutes the caller's port into the vetted
        # sockaddr (validated was resolved with port None → port 0). Scoped to
        # this synchronous request via try/finally. (Global patch — sequential
        # per agent; not for concurrent multi-host use.)
        _real_gai = socket.getaddrinfo

        def _pinned_gai(h: str, port: Any, *a: Any, **k: Any) -> list[Any]:
            if h == host:
                return [
                    (fam, typ, proto, cname, (sa[0], port) + tuple(sa[2:]))
                    for (fam, typ, proto, cname, sa) in validated
                ]
            return _real_gai(h, port, *a, **k)

        start = time.perf_counter()
        socket.getaddrinfo = _pinned_gai  # type: ignore[assignment]
        try:
            with opener.open(py_req, data=data, timeout=timeout) as resp:
                body = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise SandboxHttpError(
                        f"Response exceeds {MAX_RESPONSE_BYTES} byte cap"
                    )
                response = HttpResponse(
                    status=resp.status,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    body=body,
                    url=resp.url,
                )
        except urllib.error.HTTPError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._emit_audit(
                status="error", reason=None, url=url, duration_ms=duration_ms,
                error=f"HTTP {exc.code}: {exc.reason}",
            )
            raise SandboxHttpError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._emit_audit(
                status="error", reason=None, url=url, duration_ms=duration_ms,
                error=str(exc.reason),
            )
            raise SandboxHttpError(f"URL error: {exc.reason}") from exc
        finally:
            socket.getaddrinfo = _real_gai  # type: ignore[assignment]

        duration_ms = int((time.perf_counter() - start) * 1000)
        self._emit_audit(
            status="ok", reason=None, url=url, duration_ms=duration_ms, error=None,
        )
        return response

    # --- convenience ------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request(HttpRequest(url=url, method="GET", **kwargs))

    def post(self, url: str, json: Any = None, **kwargs: Any) -> HttpResponse:
        return self.request(HttpRequest(url=url, method="POST", json_body=json, **kwargs))

    # --- internals --------------------------------------------------------

    @staticmethod
    def _extract_host(url: str) -> str:
        try:
            return (urlparse(url).hostname or "").lower()
        except Exception:
            return ""

    def _host_allowed(self, host: str) -> bool:
        if not host:
            return False
        if not self._allowed:
            return False
        for pattern in self._allowed:
            if pattern == host:
                return True
            # Simple wildcard: "*.example.com" matches "api.example.com"
            if pattern.startswith("*.") and host.endswith(pattern[1:]):
                return True
        return False

    def _emit_audit(
        self,
        *, status: str, reason: str | None, url: str, duration_ms: int, error: str | None,
    ) -> None:
        if self._audit_sink is None:
            return
        try:
            self._audit_sink({
                "timestamp": time.time(),
                "backend": "http_client",
                "agent": self._agent,
                "action": f"http:{urlparse(url).hostname or ''}",
                "caller": "skill",
                "status": status,
                "denied_reason": reason,
                "duration_ms": duration_ms,
                "error": error,
            })
        except Exception:  # pragma: no cover
            logger.exception("Audit sink failed in http_client")
