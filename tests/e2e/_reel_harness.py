"""Fast, synchronous app+agent builder for reel-share e2e tests.

Mirrors ``test_core_loop_build_deploy``'s real-component wiring (``create_app``
+ a real :class:`~kernel.plugin_registry.PluginRegistry` on tmp dirs) but skips
the slow async ``/builder/start → answer → deploy`` HTTP flow. Instead it writes
the voice-built agent shape (``manifest.yaml`` + ``skill.yaml``) on disk and
registers it directly through the Phase-A primitive
``plugin_registry.register_dir`` — exactly what makes an agent resolvable by
``/skills/{name}/...`` (export + reel) routes.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI

from kernel.config_manager import ConfigManager
from kernel.main import create_app
from kernel.plugin_registry import PluginRegistry


def _write_agent_dir(agents_dir: Path, name: str, description: str) -> Path:
    """Write a minimal voice-built agent dir (manifest.yaml + skill.yaml).

    Args:
        agents_dir: Parent agents directory.
        name: Agent slug/name.
        description: Agent description (lands on the AgentManifest).

    Returns:
        The created agent directory.
    """
    agent_dir = agents_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "1.0.0", "description": description}
    agent_dir.joinpath("manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8"
    )
    skill_cfg = {"name": name, "description": description, "config": {}}
    agent_dir.joinpath("skill.yaml").write_text(
        yaml.safe_dump(skill_cfg, allow_unicode=True), encoding="utf-8"
    )
    return agent_dir


def build_app_with_agent(tmp_path: Path, name: str, description: str) -> FastAPI:
    """Build a FastAPI app with one agent registered and ``/skills``-resolvable.

    Args:
        tmp_path: Test tmp directory.
        name: Agent slug/name.
        description: Agent description.

    Returns:
        The configured FastAPI app (agent already registered on
        ``app.state.plugin_registry``).
    """
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(exist_ok=True)

    agent_dir = _write_agent_dir(agents_dir, name, description)

    app = create_app()
    plugin_registry = PluginRegistry(agents_dir=agents_dir)
    plugin_registry.register_dir(agent_dir)
    app.state.plugin_registry = plugin_registry

    # The reel route builds an LLMRouter from config (the intro line falls back
    # to a deterministic template when no LLM key is present). The lifespan that
    # normally wires config_manager doesn't run under ASGITransport, so set it
    # here exactly as create_app's startup does.
    config_manager = ConfigManager(Path("config/kali.yaml"))
    config_manager.load()
    app.state.config_manager = config_manager
    return app
