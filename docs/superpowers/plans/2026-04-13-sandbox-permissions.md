# Sandbox & Permissions — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add permission-based sandbox for agents — structured permissions, network proxy via JSON-RPC, filesystem enforcement, rate limiting, and approval flow.

**Architecture:** Agents declare permissions in manifests. Kernel enforces at runtime: NetworkProxy intercepts HTTP via JSON-RPC, filesystem access restricted to agent data dir, PermissionEnforcer validates before dispatch. User approves permissions via event bus (voice/UI).

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, aiohttp, pytest

**Spec:** `docs/superpowers/specs/2026-04-13-kali-ai-os-design.md` (Section 4)

---

## File Structure

```
kernel/
├── models.py                              # MODIFY: PermissionGrant, PermissionSet
├── sandbox/                               # CREATE: sandbox package
│   ├── __init__.py
│   ├── network_proxy.py                   # CREATE: HTTP proxy via JSON-RPC
│   ├── permission_enforcer.py             # CREATE: runtime permission checks
│   ├── rate_limiter.py                    # CREATE: per-agent rate limiting
│   └── approval.py                        # CREATE: user approval flow
├── agent_runtime/
│   ├── runtime.py                         # MODIFY: integrate enforcer + proxy
│   └── protocols/
│       └── native.py                      # MODIFY: handle network.request RPC
agents/
└── _base/
    └── agent_base.py                      # MODIFY: add http_request(), path enforcement
tests/
├── test_sandbox_network.py                # CREATE
├── test_sandbox_permissions.py            # CREATE
├── test_sandbox_filesystem.py             # CREATE
└── test_sandbox_rate_limiter.py           # CREATE
```

---

## Chunk 1: Structured Permission Model

### Task 1: Add PermissionGrant and PermissionSet to models

**Files:**
- Modify: `kernel/models.py`
- Test: `tests/test_sandbox_permissions.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_sandbox_permissions.py
"""Tests for permission model and enforcement."""

import pytest
from kernel.models import AgentManifest, PermissionGrant, PermissionSet


class TestPermissionModel:
    def test_permission_grant_basic(self):
        """PermissionGrant accepts valid permission name."""
        grant = PermissionGrant(name="storage")
        assert grant.name == "storage"
        assert grant.params == {}

    def test_permission_grant_with_params(self):
        """PermissionGrant accepts domain whitelist."""
        grant = PermissionGrant(
            name="network",
            params={"domains": ["api.example.com", "*.github.com"]},
        )
        assert grant.params["domains"] == ["api.example.com", "*.github.com"]

    def test_permission_set_default_not_approved(self):
        """PermissionSet defaults to not approved."""
        ps = PermissionSet(grants=[PermissionGrant(name="storage")])
        assert ps.user_approved is False

    def test_manifest_with_structured_permissions(self):
        """AgentManifest accepts structured PermissionSet."""
        manifest = AgentManifest(
            name="test",
            version="1.0.0",
            description="Test",
            protocol="native",
            permissions=PermissionSet(
                grants=[
                    PermissionGrant(name="storage"),
                    PermissionGrant(
                        name="network",
                        params={"domains": ["api.example.com"]},
                    ),
                ],
            ),
        )
        assert len(manifest.permissions.grants) == 2

    def test_manifest_backward_compat_flat_list(self):
        """AgentManifest still accepts flat list for backward compat."""
        manifest = AgentManifest(
            name="test",
            version="1.0.0",
            description="Test",
            protocol="native",
            permissions=["storage", "network"],
        )
        assert len(manifest.permissions.grants) == 2
        assert manifest.permissions.grants[0].name == "storage"
```

- [ ] **Step 2: Implement PermissionGrant and PermissionSet**

Add to `kernel/models.py`:

```python
VALID_PERMISSIONS = frozenset({
    "storage", "notifications", "event_bus", "network", "agents", "system",
})


class PermissionGrant(BaseModel):
    """Individual permission with optional parameters."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        if v not in VALID_PERMISSIONS:
            raise ValueError(f"Permission must be one of {VALID_PERMISSIONS}, got: {v}")
        return v


class PermissionSet(BaseModel):
    """Collection of permissions with approval tracking."""

    grants: list[PermissionGrant] = Field(default_factory=list)
    user_approved: bool = False
    approval_timestamp: datetime | None = None

    def has(self, name: str) -> bool:
        """Check if permission is granted."""
        return any(g.name == name for g in self.grants)

    def get_params(self, name: str) -> dict[str, Any]:
        """Get params for a permission."""
        for g in self.grants:
            if g.name == name:
                return g.params
        return {}
```

Update AgentManifest.permissions field to accept both flat list (backward compat) and PermissionSet:

```python
class AgentManifest(BaseModel):
    # ... existing fields ...
    permissions: PermissionSet = Field(default_factory=PermissionSet)

    @field_validator("permissions", mode="before")
    @classmethod
    def coerce_permissions(cls, v: Any) -> Any:
        """Accept flat list ['storage', 'network'] for backward compat."""
        if isinstance(v, list):
            grants = [
                PermissionGrant(name=p) if isinstance(p, str) else p
                for p in v
            ]
            return PermissionSet(grants=grants)
        return v
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_sandbox_permissions.py -v
```

- [ ] **Step 4: Verify existing tests still pass**

```bash
uv run pytest tests/ -v --timeout=10
```

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add structured PermissionGrant/PermissionSet with backward compat"
```

---

## Chunk 2: Rate Limiter + Network Proxy

### Task 2: Create rate limiter

**Files:**
- Create: `kernel/sandbox/__init__.py`
- Create: `kernel/sandbox/rate_limiter.py`
- Test: `tests/test_sandbox_rate_limiter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_sandbox_rate_limiter.py
"""Tests for per-agent rate limiter."""

import time
import pytest
from kernel.sandbox.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert limiter.check("agent-a") is True
        assert limiter.check("agent-a") is True
        assert limiter.check("agent-a") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.check("agent-a")
        limiter.check("agent-a")
        assert limiter.check("agent-a") is False

    def test_agents_isolated(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.check("agent-a") is True
        assert limiter.check("agent-b") is True
        assert limiter.check("agent-a") is False

    def test_window_expires(self):
        limiter = RateLimiter(max_requests=1, window_seconds=0.1)
        assert limiter.check("agent-a") is True
        assert limiter.check("agent-a") is False
        time.sleep(0.15)
        assert limiter.check("agent-a") is True

    def test_get_usage(self):
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        limiter.check("agent-a")
        limiter.check("agent-a")
        usage = limiter.get_usage("agent-a")
        assert usage["used"] == 2
        assert usage["limit"] == 10
```

- [ ] **Step 2: Implement**

```python
# kernel/sandbox/__init__.py
"""Sandbox — permission enforcement, network proxy, rate limiting."""

# kernel/sandbox/rate_limiter.py
"""Per-agent rate limiter using sliding window."""

import time
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding window rate limiter per agent."""

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}

    def check(self, agent_name: str) -> bool:
        """Check if request is allowed. Returns True if under limit."""
        now = time.monotonic()
        timestamps = self._requests.setdefault(agent_name, [])
        cutoff = now - self._window
        timestamps[:] = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= self._max:
            return False
        timestamps.append(now)
        return True

    def get_usage(self, agent_name: str) -> dict[str, Any]:
        """Get current usage for agent."""
        now = time.monotonic()
        timestamps = self._requests.get(agent_name, [])
        cutoff = now - self._window
        active = [t for t in timestamps if t > cutoff]
        return {"used": len(active), "limit": self._max, "window_seconds": self._window}
```

- [ ] **Step 3: Run tests, commit**

### Task 3: Create NetworkProxy

**Files:**
- Create: `kernel/sandbox/network_proxy.py`
- Test: `tests/test_sandbox_network.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_sandbox_network.py
"""Tests for network proxy."""

import pytest
from unittest.mock import AsyncMock, patch
from kernel.sandbox.network_proxy import NetworkProxy


class TestNetworkProxy:
    @pytest.fixture
    def proxy(self):
        p = NetworkProxy()
        p.set_allowed_domains("test-agent", ["api.example.com", "*.github.com"])
        return p

    def test_domain_allowed(self, proxy):
        assert proxy.is_domain_allowed("test-agent", "api.example.com") is True

    def test_domain_blocked(self, proxy):
        assert proxy.is_domain_allowed("test-agent", "evil.com") is False

    def test_wildcard_domain(self, proxy):
        assert proxy.is_domain_allowed("test-agent", "api.github.com") is True
        assert proxy.is_domain_allowed("test-agent", "raw.github.com") is True

    def test_unregistered_agent_blocked(self, proxy):
        assert proxy.is_domain_allowed("unknown", "api.example.com") is False

    @pytest.mark.asyncio
    async def test_handle_missing_url(self, proxy):
        result = await proxy.handle("test-agent", {"method": "GET"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_handle_blocked_domain(self, proxy):
        result = await proxy.handle("test-agent", {
            "method": "GET", "url": "https://evil.com/steal",
        })
        assert "error" in result
        assert "not in whitelist" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_rate_limited(self, proxy):
        proxy._rate_limiter._max = 1
        await proxy.handle("test-agent", {
            "method": "GET", "url": "https://api.example.com/ok",
        })
        result = await proxy.handle("test-agent", {
            "method": "GET", "url": "https://api.example.com/ok",
        })
        assert "error" in result
        assert "Rate limit" in result["error"]
```

- [ ] **Step 2: Implement NetworkProxy**

```python
# kernel/sandbox/network_proxy.py
"""Network proxy — handles 'network.request' JSON-RPC from agents."""

import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from kernel.sandbox.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class NetworkProxy:
    """Proxies HTTP requests for sandboxed agents.

    Enforces domain whitelist and rate limiting.
    Agents call via JSON-RPC 'network.request' method.
    """

    def __init__(self, max_requests_per_min: int = 60) -> None:
        self._allowed_domains: dict[str, list[str]] = {}
        self._rate_limiter = RateLimiter(
            max_requests=max_requests_per_min, window_seconds=60.0,
        )

    def set_allowed_domains(self, agent_name: str, domains: list[str]) -> None:
        """Set whitelisted domains for an agent."""
        self._allowed_domains[agent_name] = [d.lower() for d in domains]

    def is_domain_allowed(self, agent_name: str, domain: str) -> bool:
        """Check if agent can access domain."""
        patterns = self._allowed_domains.get(agent_name, [])
        domain = domain.lower()
        return any(self._match(domain, p) for p in patterns)

    async def handle(self, agent_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle network.request RPC call."""
        url = params.get("url", "").strip()
        if not url:
            return {"error": "URL is required"}

        domain = self._extract_domain(url)

        if not self.is_domain_allowed(agent_name, domain):
            logger.warning("Agent '%s' blocked from %s", agent_name, domain)
            return {"error": f"Blocked: {domain} not in whitelist"}

        if not self._rate_limiter.check(agent_name):
            logger.warning("Agent '%s' rate limited", agent_name)
            return {"error": "Rate limit exceeded"}

        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        json_body = params.get("json")
        timeout = min(int(params.get("timeout", 30)), 30)

        try:
            import urllib.request
            import json as json_mod

            req = urllib.request.Request(url, method=method)
            for k, v in headers.items():
                req.add_header(k, v)

            data = None
            if json_body is not None:
                data = json_mod.dumps(json_body).encode()
                req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
                body = resp.read().decode(errors="replace")
                logger.info("Agent '%s' → %s %s (%d)", agent_name, method, url, resp.status)
                return {"status": resp.status, "body": body}

        except Exception as e:
            logger.warning("Agent '%s' request failed: %s", agent_name, e)
            return {"error": str(e)}

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            return host.lower()
        except Exception:
            return ""

    @staticmethod
    def _match(domain: str, pattern: str) -> bool:
        """Match domain against pattern with wildcard support."""
        regex = re.escape(pattern).replace(r"\*", "[a-z0-9.-]*")
        return bool(re.fullmatch(regex, domain))
```

- [ ] **Step 3: Run tests, commit**

---

## Chunk 3: Filesystem Enforcement

### Task 4: Harden BaseAgent file access

**Files:**
- Modify: `agents/_base/agent_base.py`
- Test: `tests/test_sandbox_filesystem.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_sandbox_filesystem.py
"""Tests for filesystem sandbox in BaseAgent."""

import pytest
import json
from pathlib import Path


class ConcreteAgent:
    """Minimal agent for testing filesystem enforcement."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, filename: str) -> Path:
        if ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Invalid filename: {filename}")
        path = self._data_dir / filename
        if not path.resolve().is_relative_to(self._data_dir.resolve()):
            raise ValueError(f"Path escapes data directory: {path}")
        return path

    def _load_json(self, filename: str):
        path = self._validate_path(filename)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _save_json(self, filename: str, data):
        path = self._validate_path(filename)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


class TestFilesystemSandbox:
    @pytest.fixture
    def agent(self, tmp_path):
        return ConcreteAgent(data_dir=tmp_path / "data" / "test-agent")

    def test_normal_save_load(self, agent):
        agent._save_json("state.json", {"count": 1})
        assert agent._load_json("state.json") == {"count": 1}

    def test_path_traversal_dotdot_rejected(self, agent):
        with pytest.raises(ValueError, match="Invalid filename"):
            agent._save_json("../../../etc/passwd", {"hack": True})

    def test_path_traversal_slash_rejected(self, agent):
        with pytest.raises(ValueError, match="Invalid filename"):
            agent._save_json("other_agent/data.json", {"hack": True})

    def test_path_traversal_backslash_rejected(self, agent):
        with pytest.raises(ValueError, match="Invalid filename"):
            agent._save_json("..\\windows\\system32", {"hack": True})

    def test_load_missing_returns_none(self, agent):
        assert agent._load_json("nonexistent.json") is None
```

- [ ] **Step 2: Update BaseAgent**

In `agents/_base/agent_base.py`, add `_validate_path()` method and update `_load_json()`/`_save_json()` with path traversal checks matching the test above.

Also add `http_request()` method for network proxy:

```python
def http_request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
    """Send HTTP request through kernel proxy. Requires 'network' permission."""
    return self._rpc_call("network.request", {
        "method": method, "url": url, **kwargs,
    })

def _rpc_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call kernel RPC method via JSON-RPC on stdout/stdin."""
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 99999,
    }
    sys.stdout.write(json.dumps(request) + "\n")
    sys.stdout.flush()
    response_line = sys.stdin.readline()
    if not response_line:
        return {"error": "No response from kernel"}
    response = json.loads(response_line.strip())
    if "error" in response:
        return {"error": response["error"].get("message", str(response["error"]))}
    return response.get("result", {})
```

- [ ] **Step 3: Run tests, commit**

---

## Chunk 4: Permission Enforcer + Integration

### Task 5: Create PermissionEnforcer

**Files:**
- Create: `kernel/sandbox/permission_enforcer.py`
- Test: `tests/test_sandbox_permissions.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_sandbox_permissions.py`:

```python
from kernel.sandbox.permission_enforcer import PermissionEnforcer


class TestPermissionEnforcer:
    @pytest.fixture
    def enforcer(self):
        return PermissionEnforcer()

    def test_approved_agent_allowed(self, enforcer):
        manifest = AgentManifest(
            name="good", version="1.0.0", description="Good",
            protocol="native",
            permissions=PermissionSet(
                grants=[PermissionGrant(name="network")],
                user_approved=True,
            ),
        )
        enforcer.register_agent("good", manifest)
        assert enforcer.can_execute("good", "network.request") is True

    def test_unapproved_agent_blocked(self, enforcer):
        manifest = AgentManifest(
            name="pending", version="1.0.0", description="Pending",
            protocol="native",
            permissions=PermissionSet(
                grants=[PermissionGrant(name="network")],
                user_approved=False,
            ),
        )
        enforcer.register_agent("pending", manifest)
        assert enforcer.can_execute("pending", "network.request") is False

    def test_missing_permission_blocked(self, enforcer):
        manifest = AgentManifest(
            name="limited", version="1.0.0", description="Limited",
            protocol="native",
            permissions=PermissionSet(
                grants=[PermissionGrant(name="storage")],
                user_approved=True,
            ),
        )
        enforcer.register_agent("limited", manifest)
        assert enforcer.can_execute("limited", "network.request") is False

    def test_unregistered_agent_blocked(self, enforcer):
        assert enforcer.can_execute("unknown", "network.request") is False
```

- [ ] **Step 2: Implement PermissionEnforcer**

```python
# kernel/sandbox/permission_enforcer.py
"""Runtime permission enforcement."""

import logging
from typing import Any

from kernel.models import AgentManifest, PermissionSet

logger = logging.getLogger(__name__)

# Maps RPC method prefixes to required permissions
METHOD_PERMISSIONS: dict[str, str] = {
    "network.request": "network",
    "subscribe_event": "event_bus",
    "publish_event": "event_bus",
    "send_notification": "notifications",
    "call_agent": "agents",
    "get_system_info": "system",
}


class PermissionEnforcer:
    """Validates agent actions against approved permissions."""

    def __init__(self) -> None:
        self._permissions: dict[str, PermissionSet] = {}

    def register_agent(self, agent_name: str, manifest: AgentManifest) -> None:
        """Register agent's permissions."""
        self._permissions[agent_name] = manifest.permissions

    def can_execute(self, agent_name: str, rpc_method: str) -> bool:
        """Check if agent has permission for RPC method."""
        perms = self._permissions.get(agent_name)
        if not perms:
            return False
        if not perms.user_approved:
            return False
        required = METHOD_PERMISSIONS.get(rpc_method)
        if required is None:
            return True  # no permission needed for standard methods
        return perms.has(required)

    def get_network_domains(self, agent_name: str) -> list[str]:
        """Get allowed domains for agent."""
        perms = self._permissions.get(agent_name)
        if not perms:
            return []
        return perms.get_params("network").get("domains", [])
```

- [ ] **Step 3: Run tests, commit**

### Task 6: Wire sandbox into AgentRuntime + NativeProtocol

**Files:**
- Modify: `kernel/agent_runtime/runtime.py`
- Modify: `kernel/agent_runtime/protocols/native.py`
- Modify: `kernel/main.py`

- [ ] **Step 1: Update AgentRuntime constructor**

Add `enforcer` and `network_proxy` optional params. In `load_agent()`, register permissions and set up network domains. In `dispatch()`, check permissions before executing.

- [ ] **Step 2: Update NativeProtocol**

In `_send()`, intercept `network.request` method — route to NetworkProxy instead of forwarding to subprocess.

- [ ] **Step 3: Update kernel/main.py**

Initialize NetworkProxy and PermissionEnforcer, pass to AgentRuntime:

```python
from kernel.sandbox.network_proxy import NetworkProxy
from kernel.sandbox.permission_enforcer import PermissionEnforcer

# In startup:
network_proxy = NetworkProxy()
permission_enforcer = PermissionEnforcer()

# Pass to runtime:
runtime = AgentRuntime(
    registry=plugin_registry,
    agents_dir=Path("agents"),
    event_bus=event_bus,
    enforcer=permission_enforcer,
    network_proxy=network_proxy,
)

# Store for route access:
app.state.network_proxy = network_proxy
app.state.permission_enforcer = permission_enforcer
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/ -v --timeout=10
```

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: wire sandbox into AgentRuntime and kernel"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Structured permissions model | models.py |
| 2 | Rate limiter | sandbox/rate_limiter.py |
| 3 | Network proxy | sandbox/network_proxy.py |
| 4 | Filesystem enforcement | agent_base.py |
| 5 | Permission enforcer | sandbox/permission_enforcer.py |
| 6 | Integration wiring | runtime.py, native.py, main.py |

**Estimated time: 2-3 hours**
