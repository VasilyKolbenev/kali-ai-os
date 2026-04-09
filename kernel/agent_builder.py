"""No-Code Agent Builder — generates custom agents from natural language descriptions."""

import logging
import re
from pathlib import Path
from typing import Any

from kernel.event_bus import EventBus

logger = logging.getLogger(__name__)

CUSTOM_AGENTS_DIR = Path("agents/custom")

AGENT_TEMPLATE = '''"""Auto-generated KALI agent: {name}."""

import json
import os
import sys
import urllib.request
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class CustomAgent(BaseAgent):
    """Auto-generated agent: {description}"""

    def get_name(self) -> str:
        return "{name}"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
{action_handlers}


if __name__ == "__main__":
    CustomAgent().run()
'''

MANIFEST_TEMPLATE = """name: {name}
version: "1.0.0"
description: "{description}"
capabilities: {capabilities}
tools: {tools}
protocol: native
permissions: {permissions}
"""

# Dangerous patterns that should not appear in generated code
BLOCKED_PATTERNS = [
    r"import\s+subprocess",
    r"os\.system\s*\(",
    r"os\.remove\s*\(",
    r"os\.rmdir\s*\(",
    r"shutil\.rmtree\s*\(",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__\s*\(",
    r"open\s*\(.*['\"]w['\"]",  # writing files outside data dir
]


class AgentBuilder:
    """Generates custom agents from natural language descriptions.

    Uses LLM to understand the user's intent and generates a working
    BaseAgent subclass with the appropriate tools and logic.
    For v1, generates template-based agents without LLM (pattern matching).
    LLM-powered generation coming in v2 with Claude integration.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        CUSTOM_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    def list_custom_agents(self) -> list[dict[str, Any]]:
        """List all custom agents.

        Returns:
            List of dicts with name and description for each custom agent.
        """
        agents = []
        if not CUSTOM_AGENTS_DIR.exists():
            return agents
        for agent_dir in CUSTOM_AGENTS_DIR.iterdir():
            if agent_dir.is_dir() and (agent_dir / "manifest.yaml").exists():
                import yaml

                manifest = yaml.safe_load((agent_dir / "manifest.yaml").read_text())
                agents.append(
                    {"name": manifest["name"], "description": manifest.get("description", "")}
                )
        return agents

    def create_agent(
        self,
        name: str,
        description: str,
        tools: list[dict[str, Any]],
        action_code: str,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a custom agent from structured input.

        Args:
            name: Agent name (kebab-case)
            description: What the agent does
            tools: List of tool definitions
            action_code: Python code for handle_action method body
            permissions: Required permissions (e.g., ["network"])

        Returns:
            Status dict with agent path
        """
        # Sanitize name
        name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
        if not name:
            return {"status": "error", "message": "Invalid agent name"}

        # Safety check
        safety = self._safety_check(action_code)
        if not safety["safe"]:
            return {"status": "error", "message": f"Safety check failed: {safety['reason']}"}

        # Create directory
        agent_dir = CUSTOM_AGENTS_DIR / name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Generate agent.py
        agent_code = AGENT_TEMPLATE.format(
            name=name,
            description=description,
            action_handlers=self._indent(action_code, 8),
        )
        (agent_dir / "agent.py").write_text(agent_code, encoding="utf-8")

        # Generate manifest.yaml
        import yaml

        capabilities = [f"{name}.{t['name']}" for t in tools]
        manifest_data = {
            "name": name,
            "version": "1.0.0",
            "description": description,
            "capabilities": capabilities,
            "tools": tools,
            "protocol": "native",
            "permissions": permissions or [],
        }
        (agent_dir / "manifest.yaml").write_text(
            yaml.dump(manifest_data, default_flow_style=False), encoding="utf-8"
        )

        logger.info("Custom agent created: %s at %s", name, agent_dir)
        return {
            "status": "created",
            "name": name,
            "path": str(agent_dir),
            "tools": [t["name"] for t in tools],
        }

    def create_from_template(self, name: str, description: str, template: str) -> dict[str, Any]:
        """Create agent from a predefined template.

        Templates:
        - "monitor": Periodically checks a URL/API and alerts on conditions
        - "tracker": Tracks a value over time and reports trends
        - "notifier": Sends notifications based on triggers

        Args:
            name: Agent name (will be sanitized to kebab-case)
            description: What the agent does
            template: Template type to use

        Returns:
            Status dict with agent path
        """
        templates = {
            "monitor": self._template_monitor,
            "tracker": self._template_tracker,
            "notifier": self._template_notifier,
        }

        builder = templates.get(template)
        if not builder:
            return {
                "status": "error",
                "message": f"Unknown template: {template}. Available: {list(templates.keys())}",
            }

        return builder(name, description)

    def _template_monitor(self, name: str, description: str) -> dict[str, Any]:
        tools = [
            {"name": "check", "description": f"Check {description}", "parameters": {}},
            {"name": "get_history", "description": "Get check history", "parameters": {}},
        ]
        code = """if action == "check":
    try:
        import urllib.request
        import json
        # Override this URL in the agent's config
        url = self._config.get("url", "https://httpbin.org/get")
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        entry = {"timestamp": datetime.now().isoformat(), "status": "ok", "data": data}
        history = self._load_json("history.json") or []
        history.append(entry)
        history = history[-100:]  # keep last 100
        self._save_json("history.json", history)
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}
elif action == "get_history":
    history = self._load_json("history.json") or []
    return {"history": history, "count": len(history)}
else:
    raise ValueError(f"Unknown action: {action}")"""
        return self.create_agent(name, description, tools, code, permissions=["network"])

    def _template_tracker(self, name: str, description: str) -> dict[str, Any]:
        tools = [
            {
                "name": "log_value",
                "description": f"Log a value for {description}",
                "parameters": {"value": {"type": "number", "description": "Value to track"}},
            },
            {"name": "get_trend", "description": "Get trend data", "parameters": {}},
        ]
        code = """if action == "log_value":
    value = args.get("value", 0)
    entries = self._load_json("values.json") or []
    entries.append({"value": value, "timestamp": datetime.now().isoformat()})
    entries = entries[-365:]  # keep 1 year
    self._save_json("values.json", entries)
    return {"status": "logged", "value": value, "total_entries": len(entries)}
elif action == "get_trend":
    entries = self._load_json("values.json") or []
    if len(entries) < 2:
        return {"trend": "insufficient_data", "entries": len(entries)}
    recent = entries[-7:]
    avg = sum(e["value"] for e in recent) / len(recent)
    prev = entries[-14:-7] if len(entries) >= 14 else entries[:len(entries)//2]
    prev_avg = sum(e["value"] for e in prev) / len(prev) if prev else avg
    direction = "up" if avg > prev_avg else "down" if avg < prev_avg else "flat"
    return {
        "trend": direction, "current_avg": round(avg, 2),
        "previous_avg": round(prev_avg, 2), "entries": len(entries),
    }
else:
    raise ValueError(f"Unknown action: {action}")"""
        return self.create_agent(name, description, tools, code)

    def _template_notifier(self, name: str, description: str) -> dict[str, Any]:
        tools = [
            {
                "name": "notify",
                "description": f"Send notification about {description}",
                "parameters": {
                    "message": {"type": "string", "description": "Notification message"}
                },
            },
            {"name": "get_log", "description": "Get notification log", "parameters": {}},
        ]
        code = """if action == "notify":
    message = args.get("message", "")
    entry = {"message": message, "timestamp": datetime.now().isoformat()}
    log = self._load_json("notifications.json") or []
    log.append(entry)
    log = log[-100:]
    self._save_json("notifications.json", log)
    return {"status": "sent", "message": message}
elif action == "get_log":
    log = self._load_json("notifications.json") or []
    return {"log": log, "count": len(log)}
else:
    raise ValueError(f"Unknown action: {action}")"""
        return self.create_agent(name, description, tools, code)

    def delete_agent(self, name: str) -> dict[str, Any]:
        """Delete a custom agent.

        Args:
            name: Agent name to delete

        Returns:
            Status dict
        """
        agent_dir = CUSTOM_AGENTS_DIR / name
        if not agent_dir.exists():
            return {"status": "not_found", "name": name}
        import shutil

        shutil.rmtree(agent_dir)
        return {"status": "deleted", "name": name}

    def _safety_check(self, code: str) -> dict[str, Any]:
        """Check generated code for dangerous patterns.

        Args:
            code: Python code to validate

        Returns:
            Dict with 'safe' bool and optional 'reason'
        """
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, code):
                return {"safe": False, "reason": f"Blocked pattern found: {pattern}"}
        return {"safe": True}

    @staticmethod
    def _indent(code: str, spaces: int) -> str:
        """Indent code block.

        Args:
            code: Code string to indent
            spaces: Number of spaces to prepend to each non-empty line

        Returns:
            Indented code string
        """
        prefix = " " * spaces
        return "\n".join(prefix + line if line.strip() else line for line in code.split("\n"))
