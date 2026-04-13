"""Tests for dynamic scheduler cron registration."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from kernel.scheduler import Scheduler


class TestDynamicCron:
    @pytest.fixture
    def scheduler(self):
        bus = AsyncMock()
        config = MagicMock()
        config.morning_hour = 8
        config.evening_hour = 22
        config.timezone = "local"
        s = Scheduler(bus, config)
        return s

    def test_register_cron(self, scheduler):
        scheduler.register_cron("water-reminder", "0 */2 * * *")
        assert "water-reminder" in scheduler.list_cron_jobs()

    def test_unregister_cron(self, scheduler):
        scheduler.register_cron("test", "0 * * * *")
        scheduler.unregister_cron("test")
        assert "test" not in scheduler.list_cron_jobs()

    def test_next_run_calculated(self, scheduler):
        scheduler.register_cron("test", "0 9 * * *")
        jobs = scheduler.list_cron_jobs()
        assert jobs["test"]["next_run"] is not None
        assert isinstance(jobs["test"]["next_run"], datetime)

    def test_invalid_cron_raises(self, scheduler):
        with pytest.raises(ValueError, match="Invalid cron"):
            scheduler.register_cron("bad", "not a cron")

    def test_default_topic_uses_name(self, scheduler):
        scheduler.register_cron("daily-check", "0 8 * * *")
        jobs = scheduler.list_cron_jobs()
        assert jobs["daily-check"]["topic"] == "schedule.cron.daily-check"

    def test_custom_topic_stored(self, scheduler):
        scheduler.register_cron("ping", "*/5 * * * *", topic="my.custom.topic")
        jobs = scheduler.list_cron_jobs()
        assert jobs["ping"]["topic"] == "my.custom.topic"

    def test_unregister_nonexistent_returns_false(self, scheduler):
        assert scheduler.unregister_cron("ghost") is False

    def test_multiple_cron_jobs(self, scheduler):
        scheduler.register_cron("job-a", "0 8 * * *")
        scheduler.register_cron("job-b", "0 20 * * *")
        jobs = scheduler.list_cron_jobs()
        assert "job-a" in jobs
        assert "job-b" in jobs
        assert len(jobs) == 2

    def test_cron_expr_stored(self, scheduler):
        scheduler.register_cron("test", "30 12 * * 1-5")
        jobs = scheduler.list_cron_jobs()
        assert jobs["test"]["cron_expr"] == "30 12 * * 1-5"
