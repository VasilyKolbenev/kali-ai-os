"""Provider model registry — single machine-readable source-of-truth (OPUS-301).

The canonical data lives in ``config/model_registry.json`` and is shared, byte
for byte, with the Rust/TS/Dart consumers. This module loads and validates it at
import time (no network) and exposes read-only helpers plus a deterministic
retired-id migration.

Scope: ``anthropic`` is the enforced provider this batch. Providers absent from
the SoT (``groq``/``mistral``/…) are handled at their own call sites; every
helper is a safe no-op for them so a valid config never raises.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("kernel.model_registry")

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "model_registry.json"


def validate_registry(reg: dict[str, Any]) -> None:
    """Validate a registry dict; raise ``ValueError`` on any inconsistency.

    Checks per provider: ``default`` present and among ``models``; no duplicate
    models; ``retired`` disjoint from ``models``.

    Args:
        reg: Parsed registry mapping (``{"providers": {name: cfg}}``).

    Raises:
        ValueError: On unknown shape, missing/foreign default, duplicate model,
            or a retired id also listed as active.
    """
    providers = reg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("model_registry: 'providers' must be a non-empty object")
    for name, cfg in providers.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"model_registry: provider {name!r} must be an object")
        models = cfg.get("models")
        if not isinstance(models, list) or not models:
            raise ValueError(f"model_registry: provider {name!r} has no models")
        if len(models) != len(set(models)):
            raise ValueError(f"model_registry: provider {name!r} has duplicate models")
        default = cfg.get("default")
        if not default:
            raise ValueError(f"model_registry: provider {name!r} missing default")
        if default not in models:
            raise ValueError(
                f"model_registry: provider {name!r} default {default!r} not in models"
            )
        retired = cfg.get("retired", [])
        if not isinstance(retired, list):
            raise ValueError(f"model_registry: provider {name!r} retired must be a list")
        if default in retired:
            raise ValueError(
                f"model_registry: provider {name!r} default {default!r} is retired"
            )
        overlap = set(retired) & set(models)
        if overlap:
            raise ValueError(
                f"model_registry: provider {name!r} retired ids also active: {sorted(overlap)}"
            )


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the registry JSON.

    Args:
        path: Optional override; defaults to ``config/model_registry.json``.

    Returns:
        The validated registry dict.

    Raises:
        ValueError: If the file is missing, invalid JSON, or fails validation.
    """
    target = path or REGISTRY_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"model_registry: cannot read {target}: {e}") from e
    try:
        reg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model_registry: invalid JSON in {target}: {e}") from e
    validate_registry(reg)
    return reg


_REGISTRY: dict[str, Any] = load_registry()


def _provider(provider: str) -> dict[str, Any] | None:
    return _REGISTRY["providers"].get(provider)


def default_model(provider: str) -> str | None:
    """Return the active default model for ``provider``, or ``None`` if unmanaged."""
    cfg = _provider(provider)
    return cfg["default"] if cfg else None


def active_models(provider: str) -> list[str]:
    """Return the active (supported) models for ``provider`` (empty if unmanaged)."""
    cfg = _provider(provider)
    return list(cfg["models"]) if cfg else []


def cheap_model(provider: str) -> str | None:
    """Return the cheap/fast model for ``provider`` (e.g. key-verify pings),
    falling back to the default; ``None`` if unmanaged."""
    cfg = _provider(provider)
    if not cfg:
        return None
    return cfg.get("cheap") or cfg["default"]


def retired_models(provider: str) -> list[str]:
    """Return the retired model ids for ``provider`` (empty if unmanaged)."""
    cfg = _provider(provider)
    return list(cfg.get("retired", [])) if cfg else []


def is_retired(provider: str, model: str) -> bool:
    """True iff ``model`` is a retired id for a managed ``provider``."""
    return model in retired_models(provider)


def migrate(provider: str, model: str, *, log: bool = False) -> tuple[str, str | None]:
    """Migrate a retired ``model`` to the provider default (deterministic).

    Args:
        provider: Provider id.
        model: Currently stored model id.
        log: If True, emit a structured ``logger.warning`` on migration.

    Returns:
        ``(model, None)`` when unmanaged/active; ``(default, warning)`` when the
        stored id is retired.
    """
    if not is_retired(provider, model):
        return model, None
    new = default_model(provider)
    assert new is not None  # is_retired implies a managed provider
    warning = (
        f"Retired model {model!r} for provider {provider!r} migrated to {new!r}"
    )
    if log:
        logger.warning(
            "retired model migrated: provider=%s from=%s to=%s", provider, model, new
        )
    return new, warning
