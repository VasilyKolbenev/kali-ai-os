"""OPUS-301: provider model registry — single machine-readable SoT."""
from __future__ import annotations

import logging
import sys

import pytest

from kernel import model_registry as mr

# A minimal valid provider cfg, reused to isolate one validation violation.
_OK = {"default": "y", "cheap": "y", "models": ["y"], "retired": [], "legacy_aliases": []}


def test_anthropic_default_is_sonnet_5() -> None:
    assert mr.default_model("anthropic") == "claude-sonnet-5"


def test_cheap_is_active_haiku() -> None:
    assert mr.cheap_model("anthropic") == "claude-haiku-4-5-20251001"
    assert mr.cheap_model("anthropic") in mr.active_models("anthropic")


def test_active_models_exclude_denylist() -> None:
    active = mr.active_models("anthropic")
    assert {"claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5-20251001"} <= set(active)
    for banned in mr.denylist("anthropic"):
        assert banned not in active


def test_denylist_covers_official_retired_and_legacy_aliases() -> None:
    deny = set(mr.denylist("anthropic"))
    # official retired
    assert "claude-sonnet-4-20250514" in deny
    assert "claude-opus-4-20250514" in deny  # official retired opus 4
    # legacy UI typo aliases
    assert "claude-opus-4-20250414" in deny
    assert "claude-haiku-4-20250414" in deny


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-4-20250514",  # official retired
        "claude-opus-4-20250514",  # official retired opus 4
        "claude-opus-4-20250414",  # legacy UI typo
        "claude-haiku-4-20250414",  # legacy UI typo
    ],
)
def test_is_retired_flags_official_and_legacy(model: str) -> None:
    assert mr.is_retired("anthropic", model) is True


def test_is_retired_false_for_active() -> None:
    assert mr.is_retired("anthropic", "claude-sonnet-5") is False


def test_unknown_provider_is_noop() -> None:
    assert mr.is_retired("groq", "llama-3.3-70b-versatile") is False
    assert mr.default_model("groq") is None
    assert mr.cheap_model("groq") is None
    assert mr.migrate("groq", "llama-3.3-70b-versatile") == (
        "llama-3.3-70b-versatile",
        None,
    )


@pytest.mark.parametrize(
    "model",
    ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-opus-4-20250414"],
)
def test_migrate_retired_and_legacy_return_default_with_warning(model: str) -> None:
    new, warn = mr.migrate("anthropic", model)
    assert new == "claude-sonnet-5"
    assert warn is not None and model in warn


def test_migrate_active_is_unchanged_no_warning() -> None:
    assert mr.migrate("anthropic", "claude-sonnet-5") == ("claude-sonnet-5", None)


def test_validate_registry_passes_on_real_registry() -> None:
    mr.validate_registry(mr.load_registry())


@pytest.mark.parametrize(
    "provider_cfg, needle",
    [
        ({**_OK, "default": "x", "models": ["y"]}, "default"),  # default not in models
        ({**_OK, "models": ["y", "y"]}, "duplicate"),  # duplicate models
        ({**_OK, "models": ["y", "z"], "retired": ["z"]}, "retired"),  # retired ∩ active
        ({**_OK, "default": "y", "retired": ["y"]}, "retired"),  # default is retired
        ({"cheap": "y", "models": ["y"]}, "default"),  # missing default
        ({"default": "y", "models": ["y"]}, "cheap"),  # missing cheap
        ({**_OK, "cheap": "q"}, "cheap"),  # cheap not in models
        ({**_OK, "models": ["y", "z"], "cheap": "z", "legacy_aliases": ["z"]}, "cheap"),  # cheap denied
        ({**_OK, "models": "notalist"}, "list"),  # models not a list[str]
        ({**_OK, "legacy_aliases": ["a", "a"]}, "duplicate"),  # legacy dup
    ],
)
def test_validate_registry_rejects_bad_shapes(provider_cfg: dict, needle: str) -> None:
    bad = {"providers": {"anthropic": provider_cfg}}
    with pytest.raises(ValueError, match=needle):
        mr.validate_registry(bad)


def test_validate_registry_rejects_unknown_provider_key() -> None:
    # A key not in KNOWN_PROVIDERS inside the SoT is a typo → hard error
    # (distinct from the runtime no-op for a known-but-absent provider).
    with pytest.raises(ValueError, match="unknown provider"):
        mr.validate_registry({"providers": {"anthropicc": _OK}})


def test_validate_registry_rejects_non_dict_provider() -> None:
    with pytest.raises(ValueError):
        mr.validate_registry({"providers": {"anthropic": "not-a-dict"}})


def test_migrate_logs_structured_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="kernel.model_registry"):
        mr.migrate("anthropic", "claude-sonnet-4-20250514", log=True)
    assert any("claude-sonnet-4-20250514" in r.message for r in caplog.records)


# ── frozen-bundle path resolution (_MEIPASS) ─────────────────────────────────

def test_registry_path_prefers_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "model_registry.json").write_text(
        '{"providers":{"anthropic":{"default":"a","cheap":"a","models":["a"]}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    picked = mr._registry_path()
    assert picked == cfg_dir / "model_registry.json"
    # the file at the frozen path really loads + validates
    mr.validate_registry(mr.load_registry(picked))

    # remove the frozen marker → dev path (repo/config)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert mr._registry_path().parent.name == "config"
    assert mr._registry_path() != picked


# ── LLMConfig integration ────────────────────────────────────────────────────

def test_llmconfig_default_is_active_sonnet_5() -> None:
    from kernel.models import LLMConfig

    assert LLMConfig().cloud_model == "claude-sonnet-5"


@pytest.mark.parametrize(
    "retired", ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-opus-4-20250414"]
)
def test_llmconfig_migrates_retired_anthropic_id(retired: str) -> None:
    from kernel.models import LLMConfig

    cfg = LLMConfig(cloud_provider="anthropic", cloud_model=retired)
    assert cfg.cloud_model == "claude-sonnet-5"


def test_llmconfig_leaves_unmanaged_provider_untouched() -> None:
    from kernel.models import LLMConfig

    cfg = LLMConfig(cloud_provider="groq", cloud_model="llama-3.3-70b-versatile")
    assert cfg.cloud_model == "llama-3.3-70b-versatile"
    cfg2 = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o")
    assert cfg2.cloud_model == "gpt-4o"


# ── load-bearing consumers: values derive from the SoT (item 2) ──────────────

def test_coding_agents_derive_registry_default() -> None:
    import agents.coding.agent as coding_agent
    import agents.coding.scripts.agent as coding_script

    assert coding_agent._MODEL == mr.default_model("anthropic")
    assert coding_script._MODEL == mr.default_model("anthropic")


def test_agent_generator_fallback_derives_registry_cheap() -> None:
    from kernel.builder import agent_generator

    assert agent_generator._ANTHROPIC_FALLBACK_MODEL == mr.cheap_model("anthropic")
