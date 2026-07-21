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
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("kernel.model_registry")


def _registry_path() -> Path:
    """Resolve ``config/model_registry.json`` in both dev and frozen layouts.

    In a PyInstaller bundle the data lives under ``sys._MEIPASS/config`` (the
    build adds the whole ``config`` dir); in dev it is ``<repo>/config``. Mirrors
    the ``_MEIPASS`` idiom in ``kernel/main.py`` so a frozen import never crashes.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "config" / "model_registry.json"
    return Path(__file__).resolve().parents[1] / "config" / "model_registry.json"


REGISTRY_PATH = _registry_path()


# Provider names KALI supports. A key inside the SoT that is NOT here is a typo
# and fails validation (build-time contract). Runtime helpers still no-op for a
# known-but-absent provider (e.g. groq/mistral not yet in the SoT).
KNOWN_PROVIDERS = frozenset(
    {"anthropic", "openai", "google", "deepseek", "groq", "mistral"}
)


def _require_str_list(value: Any, name: str, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"model_registry: provider {name!r} {field} must be a list[str]")
    if len(value) != len(set(value)):
        raise ValueError(f"model_registry: provider {name!r} {field} has duplicate ids")
    return value


def validate_registry(reg: dict[str, Any]) -> None:
    """Validate a registry dict; raise ``ValueError`` on any inconsistency.

    Per provider: ``default`` present and among ``models``; ``cheap`` a non-empty
    active id; ``models``/``retired``/``legacy_aliases`` are unique ``list[str]``;
    the deny-list (retired ∪ legacy_aliases) is disjoint from ``models`` and holds
    neither ``default`` nor ``cheap``. A provider key not in ``KNOWN_PROVIDERS``
    is rejected (build-time contract distinct from the runtime no-op).

    Args:
        reg: Parsed registry mapping (``{"providers": {name: cfg}}``).

    Raises:
        ValueError: On any shape/consistency violation.
    """
    providers = reg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("model_registry: 'providers' must be a non-empty object")
    for name, cfg in providers.items():
        if name not in KNOWN_PROVIDERS:
            raise ValueError(f"model_registry: unknown provider key {name!r}")
        if not isinstance(cfg, dict):
            raise ValueError(f"model_registry: provider {name!r} must be an object")
        models = _require_str_list(cfg.get("models"), name, "models")
        if not models:
            raise ValueError(f"model_registry: provider {name!r} has no models")
        default = cfg.get("default")
        if not default or not isinstance(default, str):
            raise ValueError(f"model_registry: provider {name!r} missing default")
        if default not in models:
            raise ValueError(
                f"model_registry: provider {name!r} default {default!r} not in models"
            )
        cheap = cfg.get("cheap")
        if not cheap or not isinstance(cheap, str):
            raise ValueError(f"model_registry: provider {name!r} cheap must be a non-empty string")
        if cheap not in models:
            raise ValueError(
                f"model_registry: provider {name!r} cheap {cheap!r} not in models"
            )
        retired = _require_str_list(cfg.get("retired", []), name, "retired")
        legacy = _require_str_list(cfg.get("legacy_aliases", []), name, "legacy_aliases")
        denylist = set(retired) | set(legacy)
        if default in denylist:
            raise ValueError(
                f"model_registry: provider {name!r} default {default!r} is retired"
            )
        if cheap in denylist:
            raise ValueError(
                f"model_registry: provider {name!r} cheap {cheap!r} is retired"
            )
        overlap = denylist & set(models)
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
    """Return the official retired ids for ``provider`` (empty if unmanaged)."""
    cfg = _provider(provider)
    return list(cfg.get("retired", [])) if cfg else []


def legacy_aliases(provider: str) -> list[str]:
    """Return the legacy/typo alias ids for ``provider`` (empty if unmanaged)."""
    cfg = _provider(provider)
    return list(cfg.get("legacy_aliases", [])) if cfg else []


def denylist(provider: str) -> list[str]:
    """Return all ids that must migrate (retired ∪ legacy_aliases)."""
    return retired_models(provider) + legacy_aliases(provider)


def is_retired(provider: str, model: str) -> bool:
    """True iff ``model`` is retired or a legacy alias for a managed ``provider``."""
    return model in denylist(provider)


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
