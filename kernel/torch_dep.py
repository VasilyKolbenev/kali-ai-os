"""Torch import as a coordinator dependency (OPUS-102).

A single worker-thread import (the ModelCoordinator runs loaders on daemon
threads) with a COMPLETION-gated readiness flag — never ``sys.modules``
membership, which CPython sets at import *start* and would let a dependent race a
partially-initialised torch in the frozen bundle. Extracted to a module so tests
can inject a deterministic fake by monkeypatching :func:`load` / :func:`is_ready`.
"""
from __future__ import annotations

_ready = False


def load() -> None:
    """Import torch once (on the coordinator's daemon worker thread), then flag."""
    global _ready
    import torch  # noqa: F401

    _ready = True


def is_ready() -> bool:
    """True only after :func:`load` has fully returned."""
    return _ready
