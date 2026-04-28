"""Tests for the LLM-driven /builder/extract logic.

The actual LLM call is mocked — we test the wiring (template
validation, BuilderSession mutation contract, fallback behaviour).
"""
from __future__ import annotations

import pytest

from kernel.builder import extractor


def test_system_prompt_lists_all_template_keys() -> None:
    """Verbatim prompt mentions every template + every config key the
    helper recognises. Drift in either direction breaks A4 fast-path.
    """
    p = extractor.LLM_SYSTEM_PROMPT
    for tmpl in ("tracker", "reminder", "monitor", "notifier", "logger"):
        assert tmpl in p
    for key in (
        "interval", "goal", "notify_channel", "time_window",
        "target", "trigger", "categories",
    ):
        assert key in p
    assert "STRICT JSON" in p
