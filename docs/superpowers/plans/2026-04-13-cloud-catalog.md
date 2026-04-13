# Cloud Catalog — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package format for sharing skills/agents + catalog client for publish/search/install. Supabase backend optional — works with local export/import too.

**Architecture:** .kali-agent zip package format. CatalogClient talks to Supabase REST API. Kernel routes for publish/search/install. Local-first: packaging works offline, cloud sync when available.

**Tech Stack:** Python 3.12, zipfile, supabase-py, pytest

**Spec:** `docs/superpowers/specs/2026-04-13-kali-ai-os-design.md` (Section 5)

---

## File Structure

```
kernel/
├── catalog/                               # CREATE: catalog package
│   ├── __init__.py
│   ├── package.py                         # CREATE: .kali-agent pack/unpack
│   ├── client.py                          # CREATE: Supabase catalog client
│   └── installer.py                       # CREATE: download + verify + install
├── main.py                                # MODIFY: add /catalog/* routes
tests/
├── test_catalog_package.py                # CREATE
├── test_catalog_client.py                 # CREATE
├── test_catalog_installer.py              # CREATE
```

---

## Chunk 1: Package Format

### Task 1: .kali-agent pack/unpack

**Files:**
- Create: `kernel/catalog/__init__.py`
- Create: `kernel/catalog/package.py`
- Test: `tests/test_catalog_package.py`

Package is a zip file containing manifest.yaml + skill.yaml or agent.py + optional icon/readme.

```python
# kernel/catalog/package.py
"""Pack and unpack .kali-agent packages."""

import hashlib
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def pack(agent_dir: Path, output_path: Path | None = None) -> Path:
    """Pack an agent/skill directory into .kali-agent zip.

    Args:
        agent_dir: Directory containing manifest.yaml + (skill.yaml or agent.py)
        output_path: Where to write the zip. Default: {name}.kali-agent in cwd.

    Returns:
        Path to created .kali-agent file.
    """
    manifest_path = agent_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.yaml in {agent_dir}")

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    name = manifest.get("name", agent_dir.name)
    if output_path is None:
        output_path = Path(f"{name}.kali-agent")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in agent_dir.iterdir():
            if file.is_file() and not file.name.startswith("."):
                zf.write(file, file.name)

        # Add checksum of all files
        checksums = {}
        for file in agent_dir.iterdir():
            if file.is_file() and not file.name.startswith("."):
                checksums[file.name] = hashlib.sha256(
                    file.read_bytes()
                ).hexdigest()
        zf.writestr("checksums.json", json.dumps(checksums, indent=2))

    logger.info("Packed %s → %s", name, output_path)
    return output_path


def unpack(package_path: Path, target_dir: Path) -> Path:
    """Unpack .kali-agent zip into target directory.

    Args:
        package_path: Path to .kali-agent file
        target_dir: Parent directory (will create subdirectory from manifest name)

    Returns:
        Path to unpacked agent directory.
    """
    with zipfile.ZipFile(package_path, "r") as zf:
        # Read manifest to get name
        manifest_raw = zf.read("manifest.yaml")
        manifest = yaml.safe_load(manifest_raw)
        name = manifest.get("name", package_path.stem)

        agent_dir = target_dir / name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Extract all files except checksums.json
        for info in zf.infolist():
            if info.filename == "checksums.json":
                continue
            zf.extract(info, agent_dir)

        # Verify checksums if present
        if "checksums.json" in zf.namelist():
            checksums = json.loads(zf.read("checksums.json"))
            for filename, expected_hash in checksums.items():
                file_path = agent_dir / filename
                if file_path.exists():
                    actual_hash = hashlib.sha256(
                        file_path.read_bytes()
                    ).hexdigest()
                    if actual_hash != expected_hash:
                        raise ValueError(
                            f"Checksum mismatch for {filename}: "
                            f"expected {expected_hash[:16]}..., "
                            f"got {actual_hash[:16]}..."
                        )

    logger.info("Unpacked %s → %s", package_path, agent_dir)
    return agent_dir


def get_package_info(package_path: Path) -> dict[str, Any]:
    """Read manifest from .kali-agent without unpacking."""
    with zipfile.ZipFile(package_path, "r") as zf:
        manifest = yaml.safe_load(zf.read("manifest.yaml"))
        files = [i.filename for i in zf.infolist()]
        total_size = sum(i.file_size for i in zf.infolist())
    return {
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "description": manifest.get("description"),
        "protocol": manifest.get("protocol"),
        "files": files,
        "size_bytes": total_size,
    }
```

Tests: pack creates valid zip, unpack extracts correctly, checksum verified, corrupted file detected, get_package_info reads manifest, round-trip pack→unpack preserves content.

---

## Chunk 2: Catalog Client (Supabase)

### Task 2: Supabase catalog client

**Files:**
- Create: `kernel/catalog/client.py`
- Test: `tests/test_catalog_client.py`

Thin client over Supabase REST. All methods return dicts. Handles missing credentials gracefully (returns empty results, not crashes).

```python
# kernel/catalog/client.py
"""Supabase catalog client — search, publish, download packages."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class CatalogClient:
    """Client for KALI Cloud Catalog (Supabase backend)."""

    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL", "")
        self._key = os.environ.get("SUPABASE_KEY", "")
        self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self._url and self._key)

    def _get_client(self):
        """Lazy init Supabase client."""
        if self._client is None:
            if not self.is_configured:
                return None
            try:
                from supabase import create_client
                self._client = create_client(self._url, self._key)
            except ImportError:
                logger.warning("supabase-py not installed")
                return None
        return self._client

    async def search(
        self, query: str, category: str | None = None, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search catalog for packages."""
        client = self._get_client()
        if not client:
            return []
        try:
            q = client.table("packages").select("*").ilike(
                "name", f"%{query}%"
            )
            if category:
                q = q.eq("category", category)
            result = q.limit(limit).execute()
            return result.data or []
        except Exception as e:
            logger.warning("Catalog search failed: %s", e)
            return []

    async def get_package(self, name: str) -> dict[str, Any] | None:
        """Get package details by name."""
        client = self._get_client()
        if not client:
            return None
        try:
            result = client.table("packages").select("*").eq(
                "name", name
            ).single().execute()
            return result.data
        except Exception as e:
            logger.warning("Catalog get failed: %s", e)
            return None

    async def publish(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Publish package metadata to catalog."""
        client = self._get_client()
        if not client:
            return {"error": "Catalog not configured"}
        try:
            result = client.table("packages").upsert(metadata).execute()
            return {"status": "published", "data": result.data}
        except Exception as e:
            logger.warning("Catalog publish failed: %s", e)
            return {"error": str(e)}

    async def trending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get trending packages by downloads."""
        client = self._get_client()
        if not client:
            return []
        try:
            result = client.table("packages").select("*").order(
                "downloads", desc=True
            ).limit(limit).execute()
            return result.data or []
        except Exception as e:
            logger.warning("Catalog trending failed: %s", e)
            return []
```

Tests: mock supabase client, test search/get/publish/trending, test graceful handling when not configured.

---

## Chunk 3: Installer + Kernel Routes

### Task 3: Package installer

**Files:**
- Create: `kernel/catalog/installer.py`
- Test: `tests/test_catalog_installer.py`

Installer = unpack + safety gate + deploy. Simple orchestration.

```python
# kernel/catalog/installer.py
"""Install packages from .kali-agent files."""

import logging
from pathlib import Path
from typing import Any

from kernel.builder.safety_gate import analyze_code
from kernel.catalog.package import unpack

logger = logging.getLogger(__name__)


async def install_package(
    package_path: Path,
    agents_dir: Path,
    skill_executor: Any | None = None,
    plugin_registry: Any | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    """Install a .kali-agent package.

    1. Unpack to agents/{name}/
    2. Safety gate if agent has code
    3. Deploy (skill or agent)
    """
    try:
        agent_dir = unpack(package_path, agents_dir)
    except Exception as e:
        return {"status": "error", "message": f"Unpack failed: {e}"}

    name = agent_dir.name

    # Safety check for agents with code
    code_path = agent_dir / "agent.py"
    if code_path.exists():
        code = code_path.read_text(encoding="utf-8")
        safety = analyze_code(code)
        if not safety.safe:
            import shutil
            shutil.rmtree(agent_dir)
            return {"status": "unsafe", "name": name, "issues": safety.issues}

    # Deploy based on type
    skill_yaml = agent_dir / "skill.yaml"
    if skill_yaml.exists() and skill_executor:
        try:
            skill_executor.load_skill(agent_dir)
            return {"status": "installed", "name": name, "type": "skill"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    elif plugin_registry and agent_runtime:
        try:
            plugin_registry.discover()
            await agent_runtime.load_agent(name)
            return {"status": "installed", "name": name, "type": "agent"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "installed", "name": name, "type": "unknown"}
```

### Task 4: Kernel routes

**Modify: `kernel/main.py`**

Add minimal catalog routes:

```python
@app.post("/catalog/pack/{name}")
# Pack agent/skill into .kali-agent

@app.get("/catalog/search")
# Search cloud catalog

@app.post("/catalog/install")
# Install from .kali-agent file path

@app.post("/catalog/publish/{name}")
# Pack + publish to cloud catalog

@app.get("/catalog/info/{name}")
# Get package info without installing
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Package format | catalog/package.py |
| 2 | Catalog client | catalog/client.py |
| 3 | Installer | catalog/installer.py |
| 4 | Kernel routes | main.py |

**Estimated: 1.5-2 hours. Minimal, no overengineering.**
