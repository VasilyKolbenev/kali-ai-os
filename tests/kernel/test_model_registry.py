"""OPUS-301: provider model registry — single machine-readable SoT.

RED-first: the module does not exist yet; every test fails on import.
"""
from __future__ import annotations

import json
import logging

import pytest

from kernel import model_registry as mr


def test_anthropic_default_is_sonnet_5() -> None:
    assert mr.default_model("anthropic") == "claude-sonnet-5"


def test_active_models_exclude_retired() -> None:
    active = mr.active_models("anthropic")
    assert "claude-sonnet-5" in active
    assert "claude-opus-4-8" in active
    assert "claude-haiku-4-5-20251001" in active
    # no retired id leaks into the active list
    for retired in mr.retired_models("anthropic"):
        assert retired not in active


def test_is_retired_true_for_retired_false_for_active() -> None:
    assert mr.is_retired("anthropic", "claude-sonnet-4-20250514") is True
    assert mr.is_retired("anthropic", "claude-sonnet-5") is False


def test_unknown_provider_is_noop() -> None:
    # groq/mistral are valid providers not (yet) in the SoT — must not raise.
    assert mr.is_retired("groq", "llama-3.3-70b-versatile") is False
    assert mr.default_model("groq") is None
    assert mr.migrate("groq", "llama-3.3-70b-versatile") == (
        "llama-3.3-70b-versatile",
        None,
    )


def test_migrate_retired_returns_default_with_warning() -> None:
    new, warn = mr.migrate("anthropic", "claude-sonnet-4-20250514")
    assert new == "claude-sonnet-5"
    assert warn is not None and "claude-sonnet-4-20250514" in warn


def test_migrate_active_is_unchanged_no_warning() -> None:
    assert mr.migrate("anthropic", "claude-sonnet-5") == ("claude-sonnet-5", None)


def test_validate_registry_passes_on_real_registry() -> None:
    mr.validate_registry(mr.load_registry())


@pytest.mark.parametrize(
    "provider_cfg, needle",
    [
        # default not among models
        ({"default": "x", "models": ["y"], "retired": []}, "default"),
        # duplicate model
        ({"default": "y", "models": ["y", "y"], "retired": []}, "duplicate"),
        # retired id also listed as active
        ({"default": "y", "models": ["y", "z"], "retired": ["z"]}, "retired"),
        # default itself is retired
        ({"default": "y", "models": ["y"], "retired": ["y"]}, "retired"),
        # missing default
        ({"models": ["y"], "retired": []}, "default"),
    ],
)
def test_validate_registry_rejects_bad_shapes(provider_cfg: dict, needle: str) -> None:
    bad = {"providers": {"anthropic": provider_cfg}}
    with pytest.raises(ValueError, match=needle):
        mr.validate_registry(bad)


def test_validate_registry_rejects_unknown_provider_shape() -> None:
    with pytest.raises(ValueError):
        mr.validate_registry({"providers": {"anthropic": "not-a-dict"}})


def test_migrate_logs_structured_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="kernel.model_registry"):
        mr.migrate("anthropic", "claude-sonnet-4-20250514", log=True)
    assert any("claude-sonnet-4-20250514" in r.message for r in caplog.records)


# ── LLMConfig integration (retired-id migration on construction) ──────────────

def test_llmconfig_default_is_active_sonnet_5() -> None:
    from kernel.models import LLMConfig

    assert LLMConfig().cloud_model == "claude-sonnet-5"


def test_llmconfig_migrates_retired_anthropic_id() -> None:
    from kernel.models import LLMConfig

    cfg = LLMConfig(cloud_provider="anthropic", cloud_model="claude-sonnet-4-20250514")
    assert cfg.cloud_model == "claude-sonnet-5"


def test_llmconfig_leaves_unmanaged_provider_untouched() -> None:
    from kernel.models import LLMConfig

    # groq is a valid provider not in the SoT — must not raise or migrate.
    cfg = LLMConfig(cloud_provider="groq", cloud_model="llama-3.3-70b-versatile")
    assert cfg.cloud_model == "llama-3.3-70b-versatile"

    # openai active id stays put too.
    cfg2 = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o")
    assert cfg2.cloud_model == "gpt-4o"
