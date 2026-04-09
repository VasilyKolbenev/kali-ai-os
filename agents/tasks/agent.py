"""Tasks agent — todo and task management with local JSON storage."""

import os
import pathlib
import sys
import uuid
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class TasksAgent(BaseAgent):
    """Agent for managing tasks and todos with local JSON storage."""

    def __init__(self) -> None:
        super().__init__()
        data_dir = os.environ.get("KALI_DATA_DIR")
        if data_dir:
            self._data_dir = pathlib.Path(data_dir) / "agents" / "tasks"
            self._data_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: list[dict[str, Any]] = self._load_json("tasks.json") or []

    def get_name(self) -> str:
        return "tasks"

    def _save_tasks(self) -> None:
        self._save_json("tasks.json", self._tasks)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle task actions: add_task, list_tasks, complete_task, delete_task, get_summary.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown or task not found.
        """
        if action == "add_task":
            task: dict[str, Any] = {
                "id": str(uuid.uuid4())[:8],
                "title": args.get("title", "Untitled"),
                "priority": args.get("priority", "medium"),
                "completed": False,
                "created_at": datetime.now().isoformat(),
            }
            self._tasks.append(task)
            self._save_tasks()
            return {"status": "added", "task": task}

        elif action == "list_tasks":
            return {"tasks": self._tasks, "count": len(self._tasks)}

        elif action == "complete_task":
            task_id = args.get("task_id", "")
            for task in self._tasks:
                if task["id"] == task_id:
                    task["completed"] = True
                    task["completed_at"] = datetime.now().isoformat()
                    self._save_tasks()
                    return {"status": "completed", "task": task}
            raise ValueError(f"Task not found: {task_id}")

        elif action == "delete_task":
            task_id = args.get("task_id", "")
            self._tasks = [t for t in self._tasks if t["id"] != task_id]
            self._save_tasks()
            return {"status": "deleted", "task_id": task_id}

        elif action == "get_summary":
            done = sum(1 for t in self._tasks if t.get("completed"))
            return {
                "total": len(self._tasks),
                "done": done,
                "pending": len(self._tasks) - done,
            }

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    TasksAgent().run()
