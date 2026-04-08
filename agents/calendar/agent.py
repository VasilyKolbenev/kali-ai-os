"""Calendar agent — event scheduling with local JSON storage."""

import os
import pathlib
import sys
import uuid
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class CalendarAgent(BaseAgent):
    """Agent for managing calendar events with local JSON storage."""

    def __init__(self) -> None:
        super().__init__()
        data_dir = os.environ.get("JARVIS_DATA_DIR")
        if data_dir:
            self._data_dir = pathlib.Path(data_dir) / "agents" / "calendar"
            self._data_dir.mkdir(parents=True, exist_ok=True)
        self._events: list[dict[str, Any]] = self._load_json("events.json") or []

    def get_name(self) -> str:
        return "calendar"

    def _save_events(self) -> None:
        self._save_json("events.json", self._events)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle calendar actions: get_events, create_event, delete_event.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown.
        """
        if action == "get_events":
            date_str = args.get("date", "today")
            if date_str == "today":
                date_str = datetime.now().strftime("%Y-%m-%d")
            filtered = [e for e in self._events if e["start"].startswith(date_str)]
            return {"events": filtered, "date": date_str, "count": len(filtered)}

        elif action == "create_event":
            event: dict[str, Any] = {
                "id": str(uuid.uuid4())[:8],
                "title": args.get("title", "Untitled"),
                "start": args.get("start", ""),
                "end": args.get("end", ""),
                "created_at": datetime.now().isoformat(),
            }
            self._events.append(event)
            self._save_events()
            return {"status": "created", "event": event}

        elif action == "delete_event":
            event_id = args.get("event_id", "")
            self._events = [e for e in self._events if e["id"] != event_id]
            self._save_events()
            return {"status": "deleted", "event_id": event_id}

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    CalendarAgent().run()
