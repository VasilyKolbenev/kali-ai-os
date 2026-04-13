# AgentBuilder v2 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM-powered AgentBuilder that creates Skills and Agents from voice commands through a guided wizard, with safety gate and deployment.

**Architecture:** Intent Classifier decides skill vs agent. Voice Wizard asks 2-4 questions. Skill Generator produces YAML, Agent Generator produces Python via Claude API. Safety Gate validates code (AST analysis). Deployer writes files and registers in kernel.

**Tech Stack:** Python 3.12, anthropic SDK, ast module, pytest

**Spec:** `docs/superpowers/specs/2026-04-13-kali-ai-os-design.md` (Section 3)

---

## File Structure

```
kernel/
├── agent_builder.py                       # REWRITE: v2 with LLM generation
├── builder/                               # CREATE: builder package
│   ├── __init__.py
│   ├── intent_classifier.py               # CREATE: skill vs agent decision
│   ├── wizard.py                          # CREATE: voice wizard session
│   ├── skill_generator.py                 # CREATE: YAML skill generator
│   ├── agent_generator.py                 # CREATE: LLM code generator
│   ├── safety_gate.py                     # CREATE: AST analysis + LLM review
│   └── deployer.py                        # CREATE: file writer + registrar
tests/
├── test_builder_intent.py                 # CREATE
├── test_builder_safety.py                 # CREATE
├── test_builder_generators.py             # CREATE
├── test_builder_deployer.py               # CREATE
```

---

## Chunk 1: Intent Classifier

### Task 1: Create intent classifier

**Files:**
- Create: `kernel/builder/__init__.py`
- Create: `kernel/builder/intent_classifier.py`
- Test: `tests/test_builder_intent.py`

Intent classifier decides: is user's request a Skill (template-based) or Agent (needs code)?

Rules:
- Matches template patterns → Skill (tracker/monitor/notifier/reminder/logger)
- Needs external API → Agent
- Needs custom logic → Agent
- Ambiguous → default to Skill (safer)

```python
# kernel/builder/intent_classifier.py
"""Classify user intent as Skill or Agent."""

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATE_PATTERNS: dict[str, list[str]] = {
    "tracker": [
        r"отслеж|трек|track|учёт|учет|считай|count|log.*daily|записывай.*скольк",
        r"сколько.*выпи|потреблен|intake|расход|expens",
    ],
    "reminder": [
        r"напомин|remind|напомни|не забуд",
    ],
    "monitor": [
        r"монитор|monitor|проверяй|check.*every|следи за сайт|uptime",
    ],
    "notifier": [
        r"уведом|notify|оповест|alert|сообщ.*когда",
    ],
    "logger": [
        r"журнал|log.*event|записывай.*событ|дневник|diary",
    ],
}

AGENT_SIGNALS = [
    r"api|парс|parse|scrape|скрап|интегр|integrat",
    r"home.?assistant|умный.?дом|smart.?home",
    r"telegram|email|почт|slack|discord",
    r"код|code|github|git|программ",
    r"авиа|flight|билет|ticket|бронир|book",
    r"крипт|crypto|биржа|exchange|акци|stock",
]


@dataclass
class IntentResult:
    """Result of intent classification."""
    type: str  # "skill" or "agent"
    template: str | None  # template name if skill
    confidence: float  # 0.0 - 1.0
    reason: str


def classify(request: str) -> IntentResult:
    """Classify user request as Skill or Agent."""
    text = request.lower().strip()

    # Check template patterns first
    for template, patterns in TEMPLATE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return IntentResult(
                    type="skill",
                    template=template,
                    confidence=0.85,
                    reason=f"Matches '{template}' template pattern",
                )

    # Check agent signals
    for pattern in AGENT_SIGNALS:
        if re.search(pattern, text):
            return IntentResult(
                type="agent",
                template=None,
                confidence=0.80,
                reason=f"Requires external integration",
            )

    # Default: skill (safer, no code execution)
    return IntentResult(
        type="skill",
        template="tracker",
        confidence=0.50,
        reason="No strong signal, defaulting to skill",
    )
```

Tests should cover: tracker detection, reminder detection, agent detection (API mention), agent detection (integration mention), ambiguous defaults to skill.

---

## Chunk 2: Safety Gate (AST Analysis)

### Task 2: Create safety gate with true AST walking

**Files:**
- Create: `kernel/builder/safety_gate.py`
- Test: `tests/test_builder_safety.py`

This is security-critical. Must use `ast.NodeVisitor`, NOT string matching.

```python
# kernel/builder/safety_gate.py
"""Safety gate — validates generated agent code via AST analysis."""

import ast
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BLOCKED_IMPORTS = frozenset({
    "subprocess", "importlib", "ctypes", "multiprocessing",
    "shutil", "signal", "socket", "threading",
})

BLOCKED_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__", "getattr",
    "setattr", "delattr", "globals", "locals", "vars",
    "breakpoint", "exit", "quit",
})

BLOCKED_ATTRIBUTES = frozenset({
    "os.system", "os.popen", "os.exec", "os.spawn",
    "os.remove", "os.unlink", "os.rmdir", "os.rename",
    "os.makedirs", "os.mkdir",
})


@dataclass
class SafetyResult:
    """Result of safety analysis."""
    safe: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SafetyVisitor(ast.NodeVisitor):
    """AST visitor that checks for dangerous patterns."""

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.warnings: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module = alias.name.split(".")[0]
            if module in BLOCKED_IMPORTS:
                self.issues.append(
                    f"Line {node.lineno}: blocked import '{alias.name}'"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            module = node.module.split(".")[0]
            if module in BLOCKED_IMPORTS:
                self.issues.append(
                    f"Line {node.lineno}: blocked import from '{node.module}'"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct calls: eval(), exec(), etc.
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_BUILTINS:
                self.issues.append(
                    f"Line {node.lineno}: blocked call '{node.func.id}()'"
                )
        # Check attribute calls: os.system(), etc.
        if isinstance(node.func, ast.Attribute):
            attr_chain = self._get_attr_chain(node.func)
            if attr_chain in BLOCKED_ATTRIBUTES:
                self.issues.append(
                    f"Line {node.lineno}: blocked call '{attr_chain}()'"
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check attribute access even without call
        attr_chain = self._get_attr_chain(node)
        for blocked in BLOCKED_ATTRIBUTES:
            if attr_chain == blocked:
                self.warnings.append(
                    f"Line {node.lineno}: suspicious attribute access '{attr_chain}'"
                )
        self.generic_visit(node)

    def _get_attr_chain(self, node: ast.Attribute | ast.Name) -> str:
        """Reconstruct attribute chain: os.path.system → 'os.path.system'."""
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


def analyze_code(code: str) -> SafetyResult:
    """Analyze Python code for safety issues using AST."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return SafetyResult(safe=False, issues=[f"Syntax error: {e}"])

    visitor = SafetyVisitor()
    visitor.visit(tree)

    return SafetyResult(
        safe=len(visitor.issues) == 0,
        issues=visitor.issues,
        warnings=visitor.warnings,
    )
```

Tests must cover:
- Safe code passes
- `import subprocess` blocked
- `from os import system` blocked
- `eval()` blocked
- `os.system()` blocked
- `getattr()` blocked
- `__import__()` blocked
- Syntax error handled
- Nested `os.path.os.system` via attr chain
- `requests` import allowed (used via kernel proxy pattern later)
- Normal stdlib imports allowed

---

## Chunk 3: Generators (Skill + Agent)

### Task 3: Skill generator

**Files:**
- Create: `kernel/builder/skill_generator.py`
- Test: `tests/test_builder_generators.py`

Generates YAML files for skill based on wizard answers:

```python
# kernel/builder/skill_generator.py
"""Generate Skill YAML files from wizard spec."""

import logging
import yaml
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_skill(
    name: str,
    template: str,
    description: str,
    config: dict[str, Any],
    agents_dir: Path,
) -> Path:
    """Generate skill files in agents/{name}/ directory."""
    skill_dir = agents_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    # manifest.yaml
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "protocol": "skill",
        "capabilities": [template],
        "tools": _tools_for_template(template),
        "scheduled_events": [],
        "permissions": ["storage", "notifications"],
    }
    (skill_dir / "manifest.yaml").write_text(
        yaml.dump(manifest, allow_unicode=True, default_flow_style=False),
    )

    # skill.yaml
    skill_config = {
        "template": template,
        "display_name": description,
        "config": config,
    }
    (skill_dir / "skill.yaml").write_text(
        yaml.dump(skill_config, allow_unicode=True, default_flow_style=False),
    )

    logger.info("Generated skill '%s' (template: %s)", name, template)
    return skill_dir


def _tools_for_template(template: str) -> list[dict]:
    """Return standard tools for a template type."""
    tools_map = {
        "tracker": [
            {"name": "log", "description": "Log a value", "parameters": {"amount": {"type": "number"}}},
            {"name": "summary", "description": "Get daily summary", "parameters": {}},
            {"name": "trend", "description": "Get trend", "parameters": {}},
        ],
        "reminder": [
            {"name": "check", "description": "Check reminder", "parameters": {}},
            {"name": "snooze", "description": "Snooze", "parameters": {"minutes": {"type": "number"}}},
        ],
        "monitor": [
            {"name": "check", "description": "Check status", "parameters": {}},
            {"name": "history", "description": "Get history", "parameters": {}},
        ],
        "notifier": [
            {"name": "notify", "description": "Send notification", "parameters": {"message": {"type": "string"}}},
        ],
        "logger": [
            {"name": "log", "description": "Log event", "parameters": {"event": {"type": "string"}}},
            {"name": "search", "description": "Search", "parameters": {"query": {"type": "string"}}},
        ],
    }
    return tools_map.get(template, [])
```

### Task 4: Agent generator (Claude LLM)

**Files:**
- Create: `kernel/builder/agent_generator.py`
- Test: `tests/test_builder_generators.py` (extend)

```python
# kernel/builder/agent_generator.py
"""Generate Agent code via Claude LLM."""

import logging
import os
import re
import yaml
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are KALI AgentBuilder. Generate a Python agent.

Rules:
1. Inherit from BaseAgent (from agents._base.agent_base import BaseAgent)
2. Implement get_name() returning the agent kebab-case name
3. Implement handle_action(action, args) for each tool
4. Use self._load_json() / self._save_json() for data persistence
5. Use self.http_request(method, url) for HTTP (routed through kernel proxy)
6. NEVER use: eval, exec, subprocess, os.system, __import__, getattr, open()
7. NEVER import: subprocess, importlib, ctypes, shutil, socket
8. All functions must have type hints and docstrings
9. Handle errors with try/except, return {"error": str(e)}
10. Return dict from every action

Output ONLY the Python code, no markdown fences."""

MANIFEST_PROMPT = """Generate a manifest.yaml for this agent.

Output ONLY valid YAML, no markdown fences. Structure:
name: {name}
version: "1.0.0"
description: "{description}"
protocol: native
capabilities: [...]
tools:
  - name: tool_name
    description: "..."
    parameters:
      param: {{type: string}}
scheduled_events: []
permissions:
  - name: storage
  - name: network
    params:
      domains: [...]"""


def generate_agent(
    name: str,
    description: str,
    tools: list[dict[str, str]],
    apis: list[str],
    agents_dir: Path,
) -> Path | None:
    """Generate agent files via Claude API.

    Args:
        name: kebab-case agent name
        description: what the agent does
        tools: list of {"name": ..., "description": ...}
        apis: list of API domains needed
        agents_dir: base agents directory

    Returns:
        Path to created agent directory, or None if generation failed.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        logger.error("anthropic SDK not installed")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return None

    client = Anthropic()

    # Generate agent.py
    tools_desc = "\n".join(
        f"- {t['name']}: {t.get('description', '')}" for t in tools
    )
    user_prompt = (
        f"Create agent: {name}\n"
        f"Description: {description}\n"
        f"Tools:\n{tools_desc}\n"
        f"External APIs: {', '.join(apis) if apis else 'none'}\n"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        agent_code = response.content[0].text
        # Strip markdown fences if present
        agent_code = re.sub(r"^```python\n?", "", agent_code)
        agent_code = re.sub(r"\n?```$", "", agent_code)
    except Exception as e:
        logger.exception("Claude API failed for agent generation")
        return None

    # Generate manifest.yaml
    try:
        manifest_prompt = MANIFEST_PROMPT.format(name=name, description=description)
        response2 = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system="Output ONLY valid YAML. No markdown fences.",
            messages=[{"role": "user", "content": manifest_prompt}],
        )
        manifest_yaml = response2.content[0].text
        manifest_yaml = re.sub(r"^```ya?ml\n?", "", manifest_yaml)
        manifest_yaml = re.sub(r"\n?```$", "", manifest_yaml)
    except Exception as e:
        logger.exception("Claude API failed for manifest generation")
        return None

    # Write files
    agent_dir = agents_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.py").write_text(agent_code, encoding="utf-8")
    (agent_dir / "manifest.yaml").write_text(manifest_yaml, encoding="utf-8")

    logger.info("Generated agent '%s' via LLM", name)
    return agent_dir
```

Tests: skill_generator tested with real YAML output validation. agent_generator tested with mocked Claude API.

---

## Chunk 4: Deployer + Voice Wizard + Integration

### Task 5: Deployer

**Files:**
- Create: `kernel/builder/deployer.py`
- Test: `tests/test_builder_deployer.py`

Deploys generated skill/agent into the running system.

### Task 6: Voice Wizard

**Files:**
- Create: `kernel/builder/wizard.py`

Manages guided conversation: stores questions/answers, builds spec for generator.

### Task 7: Wire AgentBuilder v2 into main.py

**Files:**
- Modify: `kernel/agent_builder.py` (replace v1 or wrap v2)
- Modify: `kernel/main.py` (add `/builder/*` routes)

Routes:
- `POST /builder/classify` — classify intent
- `POST /builder/create-skill` — generate + deploy skill
- `POST /builder/create-agent` — generate + deploy agent (with safety gate)

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Intent classifier | builder/intent_classifier.py |
| 2 | Safety gate (AST) | builder/safety_gate.py |
| 3 | Skill generator | builder/skill_generator.py |
| 4 | Agent generator (LLM) | builder/agent_generator.py |
| 5 | Deployer | builder/deployer.py |
| 6 | Voice wizard | builder/wizard.py |
| 7 | Kernel wiring | agent_builder.py, main.py |

**Estimated time: 2-3 hours**
