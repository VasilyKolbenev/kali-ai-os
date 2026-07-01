"""Tests for skill templates."""

import pytest
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from kernel.skill_templates.base import SkillTemplate
from kernel.skill_templates.tracker import TrackerTemplate
from kernel.skill_templates.reminder import ReminderTemplate
from kernel.skill_templates.monitor import MonitorTemplate
from kernel.skill_templates.notifier import NotifierTemplate
from kernel.skill_templates.logger import LoggerTemplate


class FakeTemplate(SkillTemplate):
    """Concrete template for testing."""

    @property
    def template_name(self) -> str:
        return "fake"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "ping":
            return {"pong": True}
        return {"error": f"Unknown action: {action}"}


class TestSkillTemplateStorage:
    @pytest.fixture
    def template(self, tmp_path):
        return FakeTemplate(skill_name="test-skill", data_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_save_and_load_data(self, template):
        """Template can persist and retrieve JSON data."""
        await template.save_data("state.json", {"count": 42})
        loaded = await template.load_data("state.json")
        assert loaded == {"count": 42}

    @pytest.mark.asyncio
    async def test_load_missing_returns_default(self, template):
        """Loading non-existent file returns default."""
        loaded = await template.load_data("missing.json", default=[])
        assert loaded == []

    @pytest.mark.asyncio
    async def test_execute_action(self, template):
        """Template executes actions correctly."""
        result = await template.execute("ping", {}, {})
        assert result == {"pong": True}

    @pytest.mark.asyncio
    async def test_data_isolated_per_skill(self, tmp_path):
        """Each skill gets its own data directory."""
        t1 = FakeTemplate(skill_name="skill-a", data_dir=tmp_path)
        t2 = FakeTemplate(skill_name="skill-b", data_dir=tmp_path)
        await t1.save_data("val.json", {"x": 1})
        await t2.save_data("val.json", {"x": 2})
        assert await t1.load_data("val.json") == {"x": 1}
        assert await t2.load_data("val.json") == {"x": 2}

    @pytest.mark.asyncio
    async def test_cyrillic_roundtrip_on_windows_codepage(self, template, monkeypatch):
        """Cyrillic data round-trips exactly regardless of the OS codepage.

        Simulates a Windows non-UTF-8 default encoding (cp1252) to prove the
        save/load path forces utf-8 and never raises UnicodeEncodeError.
        """
        import locale

        monkeypatch.setattr(
            locale, "getpreferredencoding", lambda *a, **k: "cp1252",
        )
        payload = {"message": "Не забудь выпить таблетки в 9 утра"}
        await template.save_data("history.json", payload)
        loaded = await template.load_data("history.json")
        assert loaded == payload


# ---------------------------------------------------------------------------
# TrackerTemplate
# ---------------------------------------------------------------------------

class TestSkillTemplatePathSecurity:
    @pytest.fixture
    def template(self, tmp_path):
        return FakeTemplate(skill_name="test", data_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_path_traversal_dotdot_blocked(self, template):
        with pytest.raises(ValueError, match="path traversal"):
            await template.save_data("../../etc/passwd", {"x": 1})

    @pytest.mark.asyncio
    async def test_path_traversal_slash_blocked(self, template):
        with pytest.raises(ValueError, match="path traversal"):
            await template.save_data("other/file.json", {"x": 1})

    @pytest.mark.asyncio
    async def test_path_traversal_backslash_blocked(self, template):
        with pytest.raises(ValueError, match="path traversal"):
            await template.save_data("other\\file.json", {"x": 1})

    @pytest.mark.asyncio
    async def test_load_path_traversal_blocked(self, template):
        with pytest.raises(ValueError, match="path traversal"):
            await template.load_data("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_valid_filename_allowed(self, template):
        """Plain filename without path components works fine."""
        await template.save_data("data.json", {"ok": True})
        result = await template.load_data("data.json")
        assert result == {"ok": True}


class TestTrackerTemplate:
    @pytest.fixture
    def template(self, tmp_path):
        return TrackerTemplate(skill_name="steps", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {"unit": "steps", "daily_goal": 10000}

    @pytest.mark.asyncio
    async def test_template_name(self, template):
        assert template.template_name == "tracker"

    @pytest.mark.asyncio
    async def test_log_returns_total(self, template, config):
        result = await template.execute("log", {"amount": 3000}, config)
        assert result["total"] == 3000
        assert result["unit"] == "steps"

    @pytest.mark.asyncio
    async def test_log_accumulates(self, template, config):
        await template.execute("log", {"amount": 3000}, config)
        result = await template.execute("log", {"amount": 2000}, config)
        assert result["total"] == 5000

    @pytest.mark.asyncio
    async def test_summary_with_goal(self, template, config):
        await template.execute("log", {"amount": 4000}, config)
        result = await template.execute("summary", {}, config)
        assert result["total"] == 4000
        assert result["daily_goal"] == 10000
        assert result["remaining"] == 6000
        assert result["progress_pct"] == 40.0

    @pytest.mark.asyncio
    async def test_summary_no_logs(self, template, config):
        result = await template.execute("summary", {}, config)
        assert result["total"] == 0.0
        assert result["remaining"] == 10000

    @pytest.mark.asyncio
    async def test_trend_insufficient_data(self, template, config):
        result = await template.execute("trend", {}, config)
        assert result["direction"] == "insufficient_data"

    @pytest.mark.asyncio
    async def test_trend_up(self, template, config):
        """Seed 14 days of history: recent 7 days higher than prior 7."""
        today = date.today()
        history = {}
        for i in range(14):
            key = (today - timedelta(days=i)).isoformat()
            # Recent 7 days: 10000; days 7-13: 1000 — clearly trending up
            history[key] = 10000 if i < 7 else 1000
        await template.save_data("history.json", history)
        result = await template.execute("trend", {}, config)
        assert result["direction"] == "up"

    @pytest.mark.asyncio
    async def test_trend_down(self, template, config):
        today = date.today()
        history = {}
        for i in range(14):
            key = (today - timedelta(days=i)).isoformat()
            history[key] = 1000 if i < 7 else 10000
        await template.save_data("history.json", history)
        result = await template.execute("trend", {}, config)
        assert result["direction"] == "down"

    @pytest.mark.asyncio
    async def test_unknown_action(self, template, config):
        result = await template.execute("fly", {}, config)
        assert "error" in result


# ---------------------------------------------------------------------------
# ReminderTemplate
# ---------------------------------------------------------------------------

class TestReminderTemplate:
    @pytest.fixture
    def template(self, tmp_path):
        return ReminderTemplate(skill_name="water", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        # Wide window so tests always pass the hour check
        return {
            "message": "Drink water",
            "interval_hours": 0,
            "start_hour": 0,
            "end_hour": 24,
        }

    @pytest.mark.asyncio
    async def test_template_name(self, template):
        assert template.template_name == "reminder"

    @pytest.mark.asyncio
    async def test_check_fires_when_conditions_met(self, template, config):
        result = await template.execute("check", {}, config)
        assert result["should_fire"] is True
        assert result["message"] == "Drink water"

    @pytest.mark.asyncio
    async def test_check_records_history(self, template, config):
        await template.execute("check", {}, config)
        hist = await template.execute("history", {}, config)
        assert len(hist["history"]) == 1

    @pytest.mark.asyncio
    async def test_check_outside_window(self, template):
        cfg = {
            "message": "Test",
            "interval_hours": 0,
            "start_hour": 8,
            "end_hour": 9,  # narrow window — unlikely to match in tests
        }
        # Force current hour outside window by patching datetime
        fake_now = datetime(2025, 1, 1, 7, 0, 0)  # 07:00 — before start_hour
        with patch("kernel.skill_templates.reminder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await template.execute("check", {}, cfg)
        assert result["should_fire"] is False
        assert result["reason"] == "outside_window"

    @pytest.mark.asyncio
    async def test_snooze_blocks_check(self, template, config):
        # Snooze for 60 minutes
        snooze_result = await template.execute("snooze", {"minutes": 60}, config)
        assert "snoozed_until" in snooze_result

        result = await template.execute("check", {}, config)
        assert result["should_fire"] is False
        assert result["reason"] == "snoozed"

    @pytest.mark.asyncio
    async def test_snooze_returns_until(self, template, config):
        result = await template.execute("snooze", {"minutes": 30}, config)
        assert result["minutes"] == 30
        assert "snoozed_until" in result

    @pytest.mark.asyncio
    async def test_history_empty(self, template, config):
        result = await template.execute("history", {}, config)
        assert result["history"] == []

    @pytest.mark.asyncio
    async def test_unknown_action(self, template, config):
        result = await template.execute("wake", {}, config)
        assert "error" in result


# ---------------------------------------------------------------------------
# MonitorTemplate
# ---------------------------------------------------------------------------

class TestMonitorTemplate:
    @pytest.fixture(autouse=True)
    def enable_testing_mode(self, monkeypatch):
        monkeypatch.setenv("KALI_TESTING", "1")

    @pytest.fixture
    def template(self, tmp_path):
        return MonitorTemplate(skill_name="api-health", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {"url": "https://example.com", "expected_status": 200}

    @pytest.mark.asyncio
    async def test_template_name(self, template):
        assert template.template_name == "monitor"

    @pytest.mark.asyncio
    async def test_check_ok_with_mock(self, template, config):
        result = await template.execute("check", {"_mock_status": 200}, config)
        assert result["is_ok"] is True
        assert result["status_code"] == 200
        assert result["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_check_failure_detection(self, template, config):
        result = await template.execute("check", {"_mock_status": 503}, config)
        assert result["is_ok"] is False
        assert result["status_code"] == 503

    @pytest.mark.asyncio
    async def test_check_stores_history(self, template, config):
        await template.execute("check", {"_mock_status": 200}, config)
        await template.execute("check", {"_mock_status": 500}, config)
        hist = await template.execute("history", {}, config)
        assert hist["ok_count"] == 1
        assert hist["fail_count"] == 1
        assert len(hist["history"]) == 2

    @pytest.mark.asyncio
    async def test_history_empty(self, template, config):
        result = await template.execute("history", {}, config)
        assert result["history"] == []
        assert result["ok_count"] == 0
        assert result["fail_count"] == 0

    @pytest.mark.asyncio
    async def test_check_contains_checked_at(self, template, config):
        result = await template.execute("check", {"_mock_status": 200}, config)
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self, template, config):
        result = await template.execute("ping", {}, config)
        assert "error" in result


# ---------------------------------------------------------------------------
# NotifierTemplate
# ---------------------------------------------------------------------------

class TestNotifierTemplate:
    @pytest.fixture
    def template(self, tmp_path):
        return NotifierTemplate(skill_name="alerts", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {"default_channel": "voice"}

    @pytest.mark.asyncio
    async def test_template_name(self, template):
        assert template.template_name == "notifier"

    @pytest.mark.asyncio
    async def test_notify_returns_sent(self, template, config):
        result = await template.execute("notify", {"message": "Hello"}, config)
        assert result["status"] == "sent"
        assert result["message"] == "Hello"
        assert result["channel"] == "voice"

    @pytest.mark.asyncio
    async def test_notify_custom_channel(self, template, config):
        result = await template.execute(
            "notify", {"message": "Alert", "channel": "sms"}, config,
        )
        assert result["channel"] == "sms"

    @pytest.mark.asyncio
    async def test_notify_records_history(self, template, config):
        await template.execute("notify", {"message": "Msg 1"}, config)
        await template.execute("notify", {"message": "Msg 2"}, config)
        result = await template.execute("history", {}, config)
        assert len(result["history"]) == 2
        assert result["history"][0]["message"] == "Msg 1"

    @pytest.mark.asyncio
    async def test_history_empty(self, template, config):
        result = await template.execute("history", {}, config)
        assert result["history"] == []

    @pytest.mark.asyncio
    async def test_notify_contains_sent_at(self, template, config):
        result = await template.execute("notify", {"message": "Hi"}, config)
        assert "sent_at" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self, template, config):
        result = await template.execute("broadcast", {}, config)
        assert "error" in result

    # --- notify_channel honesty (WS-2) -------------------------------------

    @pytest.mark.asyncio
    async def test_notify_honors_notify_channel_key(self, template):
        """Wizard stores the chosen channel under ``notify_channel`` — honor it.

        Previously the notifier only read ``default_channel`` so the user's
        choice was silently ignored.
        """
        result = await template.execute(
            "notify", {"message": "Hi"}, {"notify_channel": "чат"},
        )
        assert result["channel"] == "чат"
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_notify_channel_arg_overrides_config(self, template):
        """An explicit ``channel`` arg beats the configured ``notify_channel``."""
        result = await template.execute(
            "notify", {"message": "Hi", "channel": "voice"}, {"notify_channel": "телеграм"},
        )
        assert result["channel"] == "voice"

    @pytest.mark.asyncio
    async def test_notify_default_channel_back_compat(self, template):
        """Legacy ``default_channel`` still works as a fallback."""
        result = await template.execute(
            "notify", {"message": "Hi"}, {"default_channel": "voice"},
        )
        assert result["channel"] == "voice"

    # --- telegram delivery honesty (WS-2) ----------------------------------

    @pytest.mark.asyncio
    async def test_telegram_unconfigured_is_not_sent(self, template, monkeypatch):
        """Telegram channel without a token must NOT claim 'sent'."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = await template.execute(
            "notify", {"message": "Alert"}, {"notify_channel": "телеграм"},
        )
        assert result["status"] != "sent"
        assert result["status"] == "unconfigured"
        assert "reason" in result
        assert result["channel"] == "телеграм"

    @pytest.mark.asyncio
    async def test_telegram_unconfigured_history_not_sent(self, template, monkeypatch):
        """The recorded history entry must also reflect the honest status."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        await template.execute("notify", {"message": "Alert"}, {"notify_channel": "telegram"})
        hist = await template.execute("history", {}, {})
        assert hist["history"][-1]["status"] == "unconfigured"

    @pytest.mark.asyncio
    async def test_telegram_configured_invokes_real_send(self, template, monkeypatch):
        """When configured, the real delivery path is invoked and status is sent."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        sent = AsyncMock(return_value={"status": "sent", "message_id": 7})
        monkeypatch.setattr(template, "_deliver_via_telegram", sent)
        result = await template.execute(
            "notify", {"message": "Alert"}, {"notify_channel": "телеграм"},
        )
        sent.assert_awaited_once_with("Alert")
        assert result["status"] == "sent"
        assert result["channel"] == "телеграм"

    @pytest.mark.asyncio
    async def test_telegram_send_failure_is_not_sent(self, template, monkeypatch):
        """A real delivery failure surfaces honestly, never as 'sent'."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        failed = AsyncMock(return_value={"status": "error", "message": "network down"})
        monkeypatch.setattr(template, "_deliver_via_telegram", failed)
        result = await template.execute(
            "notify", {"message": "Alert"}, {"notify_channel": "telegram"},
        )
        assert result["status"] != "sent"
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# LoggerTemplate
# ---------------------------------------------------------------------------

class TestLoggerTemplate:
    @pytest.fixture
    def template(self, tmp_path):
        return LoggerTemplate(skill_name="events", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {}

    @pytest.mark.asyncio
    async def test_template_name(self, template):
        assert template.template_name == "logger"

    @pytest.mark.asyncio
    async def test_log_returns_entry(self, template, config):
        result = await template.execute("log", {"event": "boot", "note": "system start"}, config)
        assert result["event"] == "boot"
        assert result["note"] == "system start"
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_log_persists(self, template, config):
        await template.execute("log", {"event": "login"}, config)
        result = await template.execute("history", {}, config)
        assert len(result["entries"]) == 1
        assert result["entries"][0]["event"] == "login"

    @pytest.mark.asyncio
    async def test_search_by_event(self, template, config):
        await template.execute("log", {"event": "user_login"}, config)
        await template.execute("log", {"event": "system_reboot"}, config)
        result = await template.execute("search", {"query": "login"}, config)
        assert result["count"] == 1
        assert result["results"][0]["event"] == "user_login"

    @pytest.mark.asyncio
    async def test_search_by_note(self, template, config):
        await template.execute("log", {"event": "task", "note": "important meeting"}, config)
        await template.execute("log", {"event": "task", "note": "routine check"}, config)
        result = await template.execute("search", {"query": "meeting"}, config)
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, template, config):
        await template.execute("log", {"event": "LoginEvent"}, config)
        result = await template.execute("search", {"query": "loginevent"}, config)
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_history_count_limit(self, template, config):
        for i in range(10):
            await template.execute("log", {"event": f"evt_{i}"}, config)
        result = await template.execute("history", {"count": 3}, config)
        assert len(result["entries"]) == 3
        assert result["total"] == 10

    @pytest.mark.asyncio
    async def test_history_empty(self, template, config):
        result = await template.execute("history", {}, config)
        assert result["entries"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_unknown_action(self, template, config):
        result = await template.execute("purge", {}, config)
        assert "error" in result
