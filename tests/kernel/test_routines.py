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
        # Honest status: events are PUBLISHED, but no agent dispatch executes them.
        assert result["status"] == "published"
        assert len(received) >= 2  # steps + completed

    async def test_execute_does_not_fake_executed(
        self, manager: RoutineManager, bus: EventBus,
    ) -> None:
        """RoutineManager must not report a green 'executed' for a no-op.

        It publishes ``routine.step`` events but dispatches nothing, so claiming
        each step was 'executed' is dishonest. Steps are reported as 'published'.
        """
        manager.create("test", [{"action": "a"}, {"action": "b"}])
        result = await manager.execute("test")
        statuses = [r["status"] for r in result["results"]]
        assert "executed" not in statuses
        assert all(s == "published" for s in statuses)

    async def test_execute_missing_routine(self, manager: RoutineManager) -> None:
        result = await manager.execute("nonexistent")
        assert result["status"] == "not_found"

    def test_delete_routine(self, manager: RoutineManager) -> None:
        manager.create("test", [])
        result = manager.delete("test")
        assert result["status"] == "deleted"


class TestRoutineManagerResilience:
    def test_corrupt_json_self_heals(
        self, bus: EventBus, tmp_path, monkeypatch,
    ) -> None:
        """A garbage routines.json must not crash boot; routines start empty."""
        import kernel.routines as routines_mod

        bad = tmp_path / "routines.json"
        bad.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(routines_mod, "ROUTINES_FILE", bad)
        mgr = RoutineManager(bus)  # must not raise
        assert mgr.list_routines() == {"routines": []}

    def test_non_dict_json_self_heals(
        self, bus: EventBus, tmp_path, monkeypatch,
    ) -> None:
        """A structurally valid but non-dict JSON is rejected to an empty map."""
        import kernel.routines as routines_mod

        bad = tmp_path / "routines.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setattr(routines_mod, "ROUTINES_FILE", bad)
        mgr = RoutineManager(bus)
        assert mgr.list_routines() == {"routines": []}

    def test_default_path_is_absolute_under_appdata(
        self, bus: EventBus, tmp_path, monkeypatch,
    ) -> None:
        """The default data path resolves under appdata_dir(), absolute."""
        import kernel.runtime_paths as rp

        monkeypatch.setattr(rp, "appdata_dir", lambda: tmp_path)
        # Re-import to recompute the module-level default from the patched dir.
        import importlib

        import kernel.routines as routines_mod

        importlib.reload(routines_mod)
        try:
            assert routines_mod.ROUTINES_FILE.is_absolute()
            assert routines_mod.ROUTINES_FILE == tmp_path / "data" / "routines.json"
            mgr = routines_mod.RoutineManager(bus)
            mgr.create("morning", [{"action": "x"}])
            assert (tmp_path / "data" / "routines.json").exists()
        finally:
            importlib.reload(routines_mod)
