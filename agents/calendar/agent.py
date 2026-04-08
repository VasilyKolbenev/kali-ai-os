"""Calendar agent — Google Calendar API with local JSON fallback."""

import os
import sys
import uuid
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class CalendarAgent(BaseAgent):
    """Agent for managing calendar events via Google Calendar or local JSON."""

    def __init__(self) -> None:
        super().__init__()
        data_dir = os.environ.get("JARVIS_DATA_DIR")
        if data_dir:
            import pathlib

            self._data_dir = pathlib.Path(data_dir) / "agents" / "calendar"
            self._data_dir.mkdir(parents=True, exist_ok=True)
        self._events: list[dict[str, Any]] = self._load_json("events.json") or []
        self._google_service: Any = None
        self._try_google_auth()

    def _try_google_auth(self) -> None:
        """Try to connect to Google Calendar API."""
        try:
            from kernel.integrations.google_auth import GoogleAuth

            auth = GoogleAuth()
            if auth.is_configured() and auth.is_authenticated():
                from googleapiclient.discovery import build

                creds = auth.get_credentials()
                self._google_service = build("calendar", "v3", credentials=creds)
        except Exception:
            self._google_service = None

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
            return self._get_events(args)
        elif action == "create_event":
            return self._create_event(args)
        elif action == "delete_event":
            return self._delete_event(args)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _get_events(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get events for a given date.

        Args:
            args: Dictionary with optional 'date' key (default 'today').

        Returns:
            Dictionary with events list, date, count, and source.
        """
        date_str = args.get("date", "today")
        if date_str == "today":
            date_str = datetime.now().strftime("%Y-%m-%d")

        if self._google_service:
            try:
                return self._get_google_events(date_str)
            except Exception:
                pass

        filtered = [e for e in self._events if e["start"].startswith(date_str)]
        return {"events": filtered, "date": date_str, "count": len(filtered), "source": "local"}

    def _get_google_events(self, date_str: str) -> dict[str, Any]:
        """Fetch events from Google Calendar.

        Args:
            date_str: Date string in YYYY-MM-DD format.

        Returns:
            Dictionary with events list, date, count, and source.
        """
        time_min = f"{date_str}T00:00:00Z"
        time_max = f"{date_str}T23:59:59Z"
        result = (
            self._google_service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = []
        for item in result.get("items", []):
            events.append(
                {
                    "id": item["id"],
                    "title": item.get("summary", "No title"),
                    "start": item["start"].get("dateTime", item["start"].get("date", "")),
                    "end": item["end"].get("dateTime", item["end"].get("date", "")),
                    "location": item.get("location", ""),
                }
            )
        return {"events": events, "date": date_str, "count": len(events), "source": "google"}

    def _create_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new calendar event.

        Args:
            args: Dictionary with 'title', 'start', and 'end' keys.

        Returns:
            Dictionary with status, event data, and source.
        """
        title = args.get("title", "Untitled")
        start = args.get("start", "")
        end = args.get("end", "")

        if self._google_service:
            try:
                event = {
                    "summary": title,
                    "start": {"dateTime": start, "timeZone": "UTC"},
                    "end": {"dateTime": end, "timeZone": "UTC"},
                }
                created = (
                    self._google_service.events()
                    .insert(calendarId="primary", body=event)
                    .execute()
                )
                return {
                    "status": "created",
                    "event": {
                        "id": created["id"],
                        "title": title,
                        "start": start,
                        "end": end,
                    },
                    "source": "google",
                }
            except Exception:
                pass

        local_event: dict[str, Any] = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "start": start,
            "end": end,
            "created_at": datetime.now().isoformat(),
        }
        self._events.append(local_event)
        self._save_events()
        return {"status": "created", "event": local_event, "source": "local"}

    def _delete_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete a calendar event by ID.

        Args:
            args: Dictionary with 'event_id' key.

        Returns:
            Dictionary with status, event_id, and source.
        """
        event_id = args.get("event_id", "")

        if self._google_service:
            try:
                self._google_service.events().delete(
                    calendarId="primary", eventId=event_id
                ).execute()
                return {"status": "deleted", "event_id": event_id, "source": "google"}
            except Exception:
                pass

        self._events = [e for e in self._events if e["id"] != event_id]
        self._save_events()
        return {"status": "deleted", "event_id": event_id, "source": "local"}


if __name__ == "__main__":
    CalendarAgent().run()
