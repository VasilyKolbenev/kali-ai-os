"""Live Canvas agent — render dynamic widgets and charts in KALI UI."""

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent

VALID_WIDGET_TYPES = frozenset({
    "stat_card",
    "bar_chart",
    "line_chart",
    "progress",
    "table",
    "markdown",
})


class LiveCanvasAgent(BaseAgent):
    """Agent that manages dynamic UI widgets on the KALI canvas.

    Widgets are stored in memory and persisted to widgets.json.
    Each render_widget call creates or updates a widget identified
    by widget_id, which the kernel then pushes to the UI via WebSocket.
    """

    def __init__(self) -> None:
        super().__init__()
        self._widgets: dict[str, dict[str, Any]] = {}
        self._load_state()

    def get_name(self) -> str:
        return "live-canvas"

    def _load_state(self) -> None:
        """Load persisted widgets from disk."""
        saved = self._load_json("widgets.json")
        if isinstance(saved, dict):
            self._widgets = saved

    def _persist_state(self) -> None:
        """Save current widgets to disk."""
        self._save_json("widgets.json", self._widgets)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle canvas actions: render_widget, clear_canvas, list_widgets.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown or widget_type is invalid.
        """
        if action == "render_widget":
            return self._render_widget(args)
        elif action == "clear_canvas":
            return self._clear_canvas()
        elif action == "list_widgets":
            return self._list_widgets()
        else:
            raise ValueError(f"Unknown action: {action}")

    def _render_widget(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create or update a widget on the canvas.

        Args:
            args: Must contain widget_type, title, data.
                  Optional widget_id for updates.

        Returns:
            Dict with status, widget_id, widget_type, and the full widget.
        """
        widget_type = args.get("widget_type", "")
        if widget_type not in VALID_WIDGET_TYPES:
            raise ValueError(
                f"Invalid widget_type '{widget_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_WIDGET_TYPES))}"
            )

        title = args.get("title", "Untitled")
        data = args.get("data", {})
        widget_id = args.get("widget_id") or str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        existing = self._widgets.get(widget_id)
        widget: dict[str, Any] = {
            "id": widget_id,
            "type": widget_type,
            "title": title,
            "data": data,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }

        self._widgets[widget_id] = widget
        self._persist_state()

        return {
            "status": "rendered",
            "widget_id": widget_id,
            "widget_type": widget_type,
            "widget": widget,
        }

    def _clear_canvas(self) -> dict[str, Any]:
        """Remove all widgets from the canvas.

        Returns:
            Dict with status and count of cleared widgets.
        """
        count = len(self._widgets)
        self._widgets.clear()
        self._persist_state()
        return {"status": "cleared", "cleared_count": count}

    def _list_widgets(self) -> dict[str, Any]:
        """List all active widgets.

        Returns:
            Dict with widgets list and count.
        """
        widgets = list(self._widgets.values())
        return {"widgets": widgets, "count": len(widgets)}


if __name__ == "__main__":
    LiveCanvasAgent().run()
