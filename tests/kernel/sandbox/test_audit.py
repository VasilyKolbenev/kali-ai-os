"""Tests for SQLite audit log."""

from __future__ import annotations

import time

import pytest

from kernel.sandbox.audit import AuditLog, AuditRecord


class TestBasicWriteRead:
    def test_write_then_query(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        rec = AuditRecord(
            timestamp=time.time(),
            backend="in_process", agent="weather", action="get_now",
        )
        log.write(rec)

        rows = log.query(limit=10)
        assert len(rows) == 1
        assert rows[0]["agent"] == "weather"
        assert rows[0]["status"] == "ok"

    def test_write_accepts_dict(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        log.write({
            "timestamp": time.time(),
            "backend": "in_process",
            "agent": "x", "action": "y",
            "status": "ok", "duration_ms": 42,
        })
        rows = log.query()
        assert rows[0]["duration_ms"] == 42

    def test_extra_fields_stored_json(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        log.write({
            "timestamp": time.time(),
            "backend": "x", "agent": "a", "action": "b",
            "custom": "value", "another": 42,
        })
        rows = log.query()
        import json
        extra = json.loads(rows[0]["extra"])
        assert extra == {"custom": "value", "another": 42}


class TestFilters:
    def _populate(self, log: AuditLog, *records: dict) -> None:
        for r in records:
            log.write(r)

    def test_filter_by_agent(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        now = time.time()
        self._populate(
            log,
            {"timestamp": now, "backend": "b", "agent": "a1", "action": "x"},
            {"timestamp": now, "backend": "b", "agent": "a2", "action": "x"},
            {"timestamp": now, "backend": "b", "agent": "a1", "action": "y"},
        )
        rows = log.query(agent="a1")
        assert len(rows) == 2
        assert all(r["agent"] == "a1" for r in rows)

    def test_filter_by_status(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        now = time.time()
        self._populate(
            log,
            {"timestamp": now, "backend": "b", "agent": "a", "action": "x", "status": "ok"},
            {"timestamp": now, "backend": "b", "agent": "a", "action": "x", "status": "denied"},
            {"timestamp": now, "backend": "b", "agent": "a", "action": "x", "status": "error"},
        )
        denied = log.query(status="denied")
        assert len(denied) == 1
        assert denied[0]["status"] == "denied"

    def test_filter_since(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        now = time.time()
        self._populate(
            log,
            {"timestamp": now - 3600, "backend": "b", "agent": "a", "action": "old"},
            {"timestamp": now, "backend": "b", "agent": "a", "action": "new"},
        )
        rows = log.query(since=now - 10)
        assert len(rows) == 1
        assert rows[0]["action"] == "new"

    def test_limit_respected(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        now = time.time()
        for i in range(20):
            log.write({"timestamp": now + i, "backend": "b", "agent": "a", "action": f"x{i}"})
        assert len(log.query(limit=5)) == 5


class TestStatsByAgent:
    def test_aggregate_counts(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        now = time.time()
        for _ in range(3):
            log.write({"timestamp": now, "backend": "b", "agent": "a", "action": "x", "status": "ok"})
        log.write({"timestamp": now, "backend": "b", "agent": "a", "action": "x", "status": "denied"})
        log.write({"timestamp": now, "backend": "b", "agent": "b", "action": "y", "status": "ok"})

        stats = log.stats_by_agent()
        stats_by_name = {s["agent"]: s for s in stats}
        assert stats_by_name["a"]["total"] == 4
        assert stats_by_name["a"]["ok_count"] == 3
        assert stats_by_name["a"]["denied_count"] == 1
        assert stats_by_name["b"]["total"] == 1

    def test_stats_respect_since(self, tmp_path):
        log = AuditLog(tmp_path / "audit.db")
        now = time.time()
        log.write({"timestamp": now - 3600, "backend": "b", "agent": "old", "action": "x"})
        log.write({"timestamp": now, "backend": "b", "agent": "new", "action": "x"})

        stats = log.stats_by_agent(since=now - 10)
        names = [s["agent"] for s in stats]
        assert names == ["new"]


class TestRetention:
    def test_prune_on_init(self, tmp_path):
        db_path = tmp_path / "audit.db"

        # Seed with old record
        log = AuditLog(db_path, retention_days=30)
        log.write({
            "timestamp": time.time() - 60 * 86400,  # 60 days ago
            "backend": "b", "agent": "old", "action": "x",
        })
        log.write({
            "timestamp": time.time(),
            "backend": "b", "agent": "new", "action": "x",
        })
        assert len(log.query()) == 2

        # Reinit with 7-day retention → prune
        log2 = AuditLog(db_path, retention_days=7)
        rows = log2.query()
        agents = [r["agent"] for r in rows]
        assert "old" not in agents
        assert "new" in agents


class TestResilience:
    def test_bad_data_does_not_raise(self, tmp_path, monkeypatch):
        log = AuditLog(tmp_path / "audit.db")

        # Force an error inside write (e.g. db path becomes invalid mid-run)
        log._db_path = tmp_path / "nonexistent" / "impossible.db"
        # Should swallow silently
        log.write({"timestamp": time.time(), "backend": "b", "agent": "a", "action": "x"})
