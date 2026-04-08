"""Tests for routine manager."""

import pytest

from kernel.event_bus import EventBus
from kernel.routines import RoutineManager


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def manager(bus: EventBus, tmp_path, monkeypatch) -> RoutineManager:
    import kernel.routines as routines_mod
    monkeypatch.setattr(routines_mod, "ROUTINES_FILE", tmp_path / "routines.json")
    return RoutineManager(bus)


class TestRoutineManager:
    def test_create_routine(self, manager: RoutineManager) -> None:
        result = manager.create("morning", [
            {"agent": "briefing", "action": "morning"},
            {"agent": "system", "action": "get_time"},
        ])
        assert result["status"] == "created"
        assert result["steps"] == 2

    def test_list_routines(self, manager: RoutineManager) -> None:
        manager.create("morning", [{"action": "test"}])
        result = manager.list_routines()
        assert len(result["routines"]) == 1

    async def test_execute_routine(self, manager: RoutineManager, bus: EventBus) -> None:
        manager.create("test", [{"action": "a"}, {"action": "b"}])
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe("routine.*", handler)
        result = await manager.execute("test")
        assert result["status"] == "completed"
        assert len(received) >= 2  # steps + completed

    async def test_execute_missing_routine(self, manager: RoutineManager) -> None:
        result = await manager.execute("nonexistent")
        assert result["status"] == "not_found"

    def test_delete_routine(self, manager: RoutineManager) -> None:
        manager.create("test", [])
        result = manager.delete("test")
        assert result["status"] == "deleted"
