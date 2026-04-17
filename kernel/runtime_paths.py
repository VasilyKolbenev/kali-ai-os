"""Helpers for runtime-specific filesystem paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KALI"


def is_frozen() -> bool:
    """Return True when running from a bundled executable."""
    return hasattr(sys, "_MEIPASS")


def project_root() -> Path:
    """Return repository root in development mode."""
    return Path(__file__).resolve().parent.parent


def executable_dir() -> Path:
    """Return the directory containing the current executable or project."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def appdata_dir() -> Path:
    """Return the writable application data directory."""
    if is_frozen():
        base = Path(os.environ.get("APPDATA", executable_dir()))
        return base / APP_NAME
    return project_root()


def models_dir() -> Path:
    """Return the effective voice models directory."""
    override = os.environ.get("KALI_MODELS_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    if is_frozen():
        sibling_models = executable_dir() / "models"
        if sibling_models.exists():
            return sibling_models
        return appdata_dir() / "models"

    return project_root() / "models"
