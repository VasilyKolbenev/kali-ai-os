"""OPUS-301 cross-language gate for the provider model registry.

Runs three checks and exits non-zero on the first failure:

1. Validate ``config/model_registry.json`` (via ``kernel.model_registry``).
2. Sync: each language mirror (Rust/TS/Dart) equals the JSON SoT for anthropic
   (default + active + retired).
3. No retired anthropic id appears in a *curated* list of production consumer
   files (defaults/options). Registry-mirror files that legitimately *declare*
   the retired list, plus build artifacts/docs, are excluded by construction.

Usage::

    python scripts/check_model_registry.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Files that DECLARE the SoT / retired ids (excluded from the retired scan).
RUST_MIRROR = REPO / "src-tauri/src/backend/config.rs"
TS_MIRROR = REPO / "ui/src/lib/modelRegistry.ts"
DART_MIRROR = REPO / "mobile/lib/standalone/llm_client.dart"

# Production CONSUMERS that must contain NO retired id (curated — never a
# repo-wide walk: excludes scratchpad/gate-stage build artifacts, docs, handoffs
# and registry-mirror files).
CONSUMER_FILES = [
    REPO / "kernel/models.py",
    REPO / "kernel/routers/system.py",
    REPO / "kernel/builder/agent_generator.py",
    REPO / "agents/coding/agent.py",
    REPO / "agents/coding/scripts/agent.py",
    REPO / "src-tauri/src/backend/config.rs",
    REPO / "ui/src/components/Settings/Settings.tsx",
    REPO / "ui/src/components/Settings/sections/LlmSettings.tsx",
    REPO / "config/kali.yaml",
]


# Load-bearing consumers: they must DERIVE the model from the registry (never a
# literal), so a JSON default/cheap change moves them in lockstep. Each maps a
# file → the registry call it must contain. The gate also asserts the derived
# assignment line carries no ``claude-`` literal (drift vector).
LOAD_BEARING = {
    REPO / "agents/coding/agent.py": 'default_model("anthropic")',
    REPO / "agents/coding/scripts/agent.py": 'default_model("anthropic")',
    REPO / "kernel/builder/agent_generator.py": 'cheap_model("anthropic")',
}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _denylist(anthropic: dict) -> list[str]:
    """All ids that must never appear active: official retired ∪ legacy aliases."""
    return list(anthropic.get("retired", [])) + list(anthropic.get("legacy_aliases", []))


def _load_sot() -> dict:
    sys.path.insert(0, str(REPO))
    from kernel.model_registry import load_registry, validate_registry

    reg = load_registry()
    validate_registry(reg)
    return reg["providers"]["anthropic"]


def _check_rust(anthropic: dict) -> None:
    text = RUST_MIRROR.read_text(encoding="utf-8")
    m = re.search(r'cloud_model:\s*"([^"]+)"\.to_string\(\)', text)
    if not m:
        _fail(f"{RUST_MIRROR.name}: cloud_model literal not found")
    if m.group(1) != anthropic["default"]:
        _fail(
            f"{RUST_MIRROR.name}: cloud_model {m.group(1)!r} != SoT {anthropic['default']!r}"
        )


def _extract_ts_list(text: str, name: str) -> list[str]:
    m = re.search(rf"{name}\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        _fail(f"{TS_MIRROR.name}: {name} not found")
    return re.findall(r'"([^"]+)"', m.group(1))


def _check_ts(anthropic: dict) -> None:
    text = TS_MIRROR.read_text(encoding="utf-8")
    m = re.search(r'ANTHROPIC_DEFAULT\s*=\s*"([^"]+)"', text)
    if not m or m.group(1) != anthropic["default"]:
        _fail(f"{TS_MIRROR.name}: ANTHROPIC_DEFAULT != SoT")
    if _extract_ts_list(text, "ANTHROPIC_ACTIVE") != anthropic["models"]:
        _fail(f"{TS_MIRROR.name}: ANTHROPIC_ACTIVE != SoT models")
    if sorted(_extract_ts_list(text, "ANTHROPIC_RETIRED")) != sorted(_denylist(anthropic)):
        _fail(f"{TS_MIRROR.name}: ANTHROPIC_RETIRED != SoT deny-list (retired ∪ legacy)")


def _check_dart(anthropic: dict) -> None:
    text = DART_MIRROR.read_text(encoding="utf-8")
    m = re.search(r"kAnthropicDefaultModel\s*=\s*'([^']+)'", text)
    if not m or m.group(1) != anthropic["default"]:
        _fail(f"{DART_MIRROR.name}: kAnthropicDefaultModel != SoT")
    block = re.search(r"kAnthropicRetiredModels\s*=\s*<String>\[(.*?)\]", text, re.S)
    if not block:
        _fail(f"{DART_MIRROR.name}: kAnthropicRetiredModels not found")
    retired = re.findall(r"'([^']+)'", block.group(1))
    if sorted(retired) != sorted(_denylist(anthropic)):
        _fail(f"{DART_MIRROR.name}: kAnthropicRetiredModels != SoT deny-list (retired ∪ legacy)")


def _check_no_retired_in_consumers(anthropic: dict) -> None:
    for f in CONSUMER_FILES:
        text = f.read_text(encoding="utf-8")
        for rid in _denylist(anthropic):
            if rid in text:
                _fail(f"{f.relative_to(REPO)}: retired id {rid!r} present in a consumer")


def _check_consumers_load_bearing(anthropic: dict) -> None:
    """Coding agents / builder must DERIVE the model from the registry, so a JSON
    default/cheap change moves them in lockstep (a plain retired-scan can't prove
    this). Assert the derive-call is present and the model line has no literal."""
    for f, call in LOAD_BEARING.items():
        text = f.read_text(encoding="utf-8")
        if call not in text:
            _fail(f"{f.relative_to(REPO)}: must derive from registry via {call}")
        # the assignment that feeds the model must not carry a hardcoded id
        for line in text.splitlines():
            is_model_line = ("_MODEL" in line or "_ANTHROPIC_FALLBACK_MODEL" in line) and "=" in line
            if is_model_line and "claude-" in line:
                _fail(f"{f.relative_to(REPO)}: hardcoded model id on {line.strip()!r}")


def main() -> None:
    anthropic = _load_sot()
    _check_rust(anthropic)
    _check_ts(anthropic)
    _check_dart(anthropic)
    _check_no_retired_in_consumers(anthropic)
    _check_consumers_load_bearing(anthropic)
    print(
        "OK: registry validated; mirrors + consumers in sync; "
        "no retired/legacy id in consumers"
    )


if __name__ == "__main__":
    main()
