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


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


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
    if _extract_ts_list(text, "ANTHROPIC_RETIRED") != anthropic["retired"]:
        _fail(f"{TS_MIRROR.name}: ANTHROPIC_RETIRED != SoT retired")


def _check_dart(anthropic: dict) -> None:
    text = DART_MIRROR.read_text(encoding="utf-8")
    m = re.search(r"kAnthropicDefaultModel\s*=\s*'([^']+)'", text)
    if not m or m.group(1) != anthropic["default"]:
        _fail(f"{DART_MIRROR.name}: kAnthropicDefaultModel != SoT")
    block = re.search(r"kAnthropicRetiredModels\s*=\s*<String>\[(.*?)\]", text, re.S)
    if not block:
        _fail(f"{DART_MIRROR.name}: kAnthropicRetiredModels not found")
    retired = re.findall(r"'([^']+)'", block.group(1))
    if retired != anthropic["retired"]:
        _fail(f"{DART_MIRROR.name}: kAnthropicRetiredModels != SoT retired")


def _check_no_retired_in_consumers(anthropic: dict) -> None:
    retired = anthropic["retired"]
    for f in CONSUMER_FILES:
        text = f.read_text(encoding="utf-8")
        for rid in retired:
            if rid in text:
                _fail(f"{f.relative_to(REPO)}: retired id {rid!r} present in a consumer")


def main() -> None:
    anthropic = _load_sot()
    _check_rust(anthropic)
    _check_ts(anthropic)
    _check_dart(anthropic)
    _check_no_retired_in_consumers(anthropic)
    print("OK: model registry validated, mirrors in sync, no retired id in consumers")


if __name__ == "__main__":
    main()
