"""Routine automation — named sequences of actions."""

import json
import logging
from pathlib import Path
from typing import Any

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)

ROUTINES_FILE = Path("data/routines.json")


class RoutineManager:
    """Manages and executes named action sequences (routines)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._routines: dict[str, list[dict[str, Any]]] = self._load()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if ROUTINES_FILE.exists():
            return json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))
        return {}

    def _save(self) -> None:
        ROUTINES_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROUTINES_FILE.write_text(json.dumps(self._routines, indent=2), encoding="utf-8")

    def create(self, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Create or overwrite a named routine.

        Args:
            name: Routine identifier.
            steps: Ordered list of step dicts (agent, action, params, etc.).

        Returns:
            Dict with status, name, steps count.
        """
        self._routines[name] = steps
        self._save()
        return {"status": "created", "name": name, "steps": len(steps)}

    def delete(self, name: str) -> dict[str, Any]:
        """Delete a named routine.

        Args:
            name: Routine identifier.

        Returns:
            Dict with status and name.
        """
        if name in self._routines:
            del self._routines[name]
            self._save()
            return {"status": "deleted", "name": name}
        return {"status": "not_found", "name": name}

    def list_routines(self) -> dict[str, Any]:
        """List all routines with step counts.

        Returns:
            Dict with 'routines' list of name/steps dicts.
        """
        return {
            "routines": [
                {"name": name, "steps": len(steps)}
                for name, steps in self._routines.items()
            ]
        }

    async def execute(self, name: str) -> dict[str, Any]:
        """Publish a ``routine.step`` event for each step of a named routine.

        This does NOT dispatch steps to agents — there is no ``agent_runtime``
        wiring here — so each step is reported as ``"published"`` (the event
        was emitted), never ``"executed"``. Reporting ``"executed"`` would be a
        fake green status for a no-op; honest status is the rule.

        Args:
            name: Routine identifier.

        Returns:
            Dict with status (``"published"`` / ``"not_found"``), name, and a
            results list whose entries carry the honest per-step status.
        """
        steps = self._routines.get(name)
        if not steps:
            return {"status": "not_found", "name": name}

        results = []
        for step in steps:
            await self._bus.publish(Event(
                topic="routine.step",
                source="routine-manager",
                payload={"routine": name, "step": step},
            ))
            results.append({"step": step, "status": "published"})

        await self._bus.publish(Event(
            topic="routine.completed",
            source="routine-manager",
            payload={"routine": name, "steps_published": len(results)},
        ))

        return {"status": "published", "name": name, "results": results}
