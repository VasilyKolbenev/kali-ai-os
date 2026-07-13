"""Cross-router helpers shared by the extracted domain routers.

Everything here is app-parameterized (no closure over create_app locals) —
the routers and main.py both import from this module, never from each other.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _mask_key(key: str) -> str:
    """Mask API key for display: sk-abc***xyz."""
    if not key or len(key) < 8:
        return ""
    return f"{key[:7]}***{key[-4:]}"


def _save_env(updates: dict[str, str]) -> None:
    """Save/update keys in .env file.

    In frozen (PyInstaller) mode writes to %APPDATA%/KALI/.env,
    otherwise to the project root .env.
    """
    if hasattr(sys, "_MEIPASS"):
        env_path = Path(os.environ.get("APPDATA", "")) / "KALI" / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        env_path = Path(".env")
    # Guard the .env boundary: a newline or other control char in a value would
    # inject a spurious KEY=VALUE line (e.g. token='x\nADMIN=1'). Reject rather
    # than silently corrupt the environment file.
    for k, v in updates.items():
        if any(ord(c) < 0x20 for c in f"{k}{v}"):
            raise ValueError(f"Control character not allowed in env entry: {k!r}")
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    existing.update(updates)
    env_path.write_text(
        "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8"
    )


def _play_audio(audio: Any, sr: int) -> None:
    """Play audio through system speakers via sounddevice."""
    import numpy as np
    import sounddevice as sd

    # Ensure float32 for sounddevice
    if not isinstance(audio, np.ndarray):
        audio = np.array(audio, dtype=np.float32)
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    sd.play(audio, sr)
    sd.wait()


def _get_skills_catalog(app: Any):
    """Lazy-init the remote SkillsCatalog singleton."""
    from kernel.skills.catalog import SkillsCatalog

    if not hasattr(app.state, "skills_catalog"):
        app.state.skills_catalog = SkillsCatalog()
    return app.state.skills_catalog


def _get_skills_registry(app: Any):
    """Lazy-init the local SkillsRegistry singleton (hybrid builtin + user)."""
    from kernel.skills.registry import SkillsRegistry

    if not hasattr(app.state, "skills_registry"):
        reg = SkillsRegistry()
        reg.discover()
        app.state.skills_registry = reg
    return app.state.skills_registry


def _get_sandbox(app: Any):
    """Lazy-init the SandboxBackend singleton with enforcer + limiter + audit."""
    if hasattr(app.state, "sandbox"):
        return app.state.sandbox

    from kernel.sandbox.audit import AuditLog
    from kernel.sandbox.backend import InProcessSandbox
    from kernel.sandbox.rate_limiter import RateLimiter

    audit_db = app.state.db_path.parent / "sandbox_audit.db"
    audit_log = AuditLog(audit_db, retention_days=30)
    rate_limiter = RateLimiter(max_requests=120, window_seconds=60.0)

    sandbox = InProcessSandbox(
        agent_runtime=app.state.agent_runtime,
        enforcer=getattr(app.state, "permission_enforcer", None),
        rate_limiter=rate_limiter,
        audit_sink=audit_log.write,
    )

    app.state.sandbox = sandbox
    app.state.sandbox_audit = audit_log
    app.state.sandbox_rate_limiter = rate_limiter
    return sandbox
