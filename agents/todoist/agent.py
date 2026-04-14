"""Todoist agent — manage tasks via Todoist REST API v2."""

import json
import logging
import os
import sys
import urllib.request
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent

logger = logging.getLogger(__name__)

BASE_URL = "https://api.todoist.com/rest/v2"


class TodoistAgent(BaseAgent):
    """Agent for managing Todoist tasks."""

    def __init__(self) -> None:
        super().__init__()
        self._api_key = ""

    def get_name(self) -> str:
        """Return agent name."""
        return "todoist"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (get_tasks, add_task, complete_task).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        self._api_key = os.environ.get("TODOIST_API_KEY", "")
        if not self._api_key:
            return {"error": "Set TODOIST_API_KEY in Settings to enable this agent"}

        if action == "get_tasks":
            return self._get_tasks()
        elif action == "add_task":
            return self._add_task(
                args.get("content", ""),
                args.get("priority", 1),
                args.get("due_string"),
            )
        elif action == "complete_task":
            return self._complete_task(args.get("task_id", ""))
        else:
            raise ValueError(f"Unknown action: {action}")

    def _api_call(self, method: str, path: str, body: dict | None = None) -> Any:
        """Make a Todoist API call.

        Args:
            method: HTTP method (GET, POST).
            path: API path (e.g. '/tasks').
            body: Optional request body.

        Returns:
            Parsed response (list or dict), or dict with 'error' key on failure.
        """
        url = f"{BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, method=method, headers=headers)
        if body is not None:
            req.data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read().decode()}"}
        except Exception as e:
            return {"error": str(e)}

    def _get_tasks(self) -> dict[str, Any]:
        """List active Todoist tasks.

        Returns:
            Dict with list of tasks.
        """
        result = self._api_call("GET", "/tasks")
        if isinstance(result, dict) and "error" in result:
            return result
        tasks = []
        for t in result:
            tasks.append({
                "id": t.get("id"),
                "content": t.get("content"),
                "priority": t.get("priority"),
                "due": t.get("due", {}).get("string") if t.get("due") else None,
                "project_id": t.get("project_id"),
            })
        return {"tasks": tasks, "count": len(tasks)}

    def _add_task(self, content: str, priority: int = 1, due_string: str | None = None) -> dict[str, Any]:
        """Create a new Todoist task.

        Args:
            content: Task text content.
            priority: Priority 1-4 (4 = urgent).
            due_string: Natural language due date (e.g. 'tomorrow').

        Returns:
            Dict with new task id and content.
        """
        if not content:
            return {"error": "content is required"}
        body: dict[str, Any] = {"content": content, "priority": priority}
        if due_string:
            body["due_string"] = due_string
        result = self._api_call("POST", "/tasks", body)
        if isinstance(result, dict) and "error" in result:
            return result
        return {"id": result.get("id"), "content": result.get("content"), "created": True}

    def _complete_task(self, task_id: str) -> dict[str, Any]:
        """Close (complete) a Todoist task.

        Args:
            task_id: Task ID to close.

        Returns:
            Dict with completed status.
        """
        if not task_id:
            return {"error": "task_id is required"}
        result = self._api_call("POST", f"/tasks/{task_id}/close")
        if isinstance(result, dict) and "error" in result:
            return result
        return {"task_id": task_id, "completed": True}


if __name__ == "__main__":
    TodoistAgent().run()
