# Skill Engine — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Skill system — lightweight YAML-configured automations (tracker, monitor, notifier, reminder, logger) that run in-process, with dynamic cron scheduling.

**Architecture:** Skills are YAML configs that parameterize built-in template classes. SkillExecutor runs them in-process (no subprocess). Scheduler extended with dynamic cron registration via croniter. PluginRegistry discovers skills alongside agents but routes them to SkillExecutor.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, croniter, pytest

**Spec:** `docs/superpowers/specs/2026-04-13-kali-ai-os-design.md` (Section 2)

---

## File Structure

```
kernel/
├── models.py                          # MODIFY: add "skill" protocol, SkillConfig model
├── scheduler.py                       # MODIFY: add dynamic cron/interval registration
├── plugin_registry.py                 # MODIFY: route skill protocol to SkillExecutor
├── skill_executor.py                  # CREATE: in-process skill runner
├── skill_templates/                   # CREATE: template implementations
│   ├── __init__.py
│   ├── base.py                        # CREATE: SkillTemplate ABC
│   ├── tracker.py                     # CREATE: tracker template
│   ├── monitor.py                     # CREATE: monitor template
│   ├── notifier.py                    # CREATE: notifier template
│   ├── reminder.py                    # CREATE: reminder template
│   └── logger.py                      # CREATE: logger template
├── main.py                            # MODIFY: add skill routes + init
├── agent_runtime/
│   └── runtime.py                     # MODIFY: skip "skill" protocol
tests/
├── test_skill_executor.py             # CREATE
├── test_skill_templates.py            # CREATE
├── test_scheduler_dynamic.py          # CREATE
agents/
└── (example skills created during testing)
```

---

## Chunk 1: Models & Protocol Registration

### Task 1: Add "skill" protocol to AgentManifest

**Files:**
- Modify: `kernel/models.py`
- Test: `tests/test_skill_executor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_skill_executor.py
"""Tests for Skill Engine."""

import pytest
from kernel.models import AgentManifest


class TestSkillProtocol:
    def test_skill_protocol_is_valid(self):
        """AgentManifest accepts 'skill' as valid protocol."""
        manifest = AgentManifest(
            name="test-skill",
            version="1.0.0",
            description="Test skill",
            protocol="skill",
        )
        assert manifest.protocol == "skill"

    def test_invalid_protocol_still_rejected(self):
        """Unknown protocols are still rejected."""
        with pytest.raises(ValueError, match="Protocol must be one of"):
            AgentManifest(
                name="bad",
                version="1.0.0",
                description="Bad",
                protocol="invalid",
            )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\Users\User\Desktop\Jarvis
uv run pytest tests/test_skill_executor.py::TestSkillProtocol::test_skill_protocol_is_valid -v
```

Expected: FAIL — `ValueError: Protocol must be one of {'native', 'mcp', 'http'}`

- [ ] **Step 3: Add "skill" to valid protocols**

In `kernel/models.py`, find the `protocol_must_be_valid` validator and change:

```python
valid = {"native", "mcp", "http"}
```
to:
```python
valid = {"native", "mcp", "http", "skill"}
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_skill_executor.py::TestSkillProtocol -v
```

Expected: 2 PASS

- [ ] **Step 5: Update AgentRuntime to skip skills**

In `kernel/agent_runtime/runtime.py`, in `_create_protocol()` method, add before the `else` branch:

```python
elif manifest.protocol == "skill":
    raise ValueError(
        f"Skill '{manifest.name}' handled by SkillExecutor, not AgentRuntime"
    )
```

- [ ] **Step 6: Commit**

```bash
git add kernel/models.py kernel/agent_runtime/runtime.py tests/test_skill_executor.py
git commit -m "feat: add 'skill' protocol to AgentManifest"
```

---

## Chunk 2: SkillTemplate Base & Data Storage

### Task 2: Create SkillTemplate ABC and storage

**Files:**
- Create: `kernel/skill_templates/__init__.py`
- Create: `kernel/skill_templates/base.py`
- Test: `tests/test_skill_templates.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_skill_templates.py
"""Tests for skill templates."""

import json
import pytest
from pathlib import Path
from kernel.skill_templates.base import SkillTemplate


class FakeTemplate(SkillTemplate):
    """Concrete template for testing."""

    @property
    def template_name(self) -> str:
        return "fake"

    async def execute(self, action: str, args: dict, config: dict) -> dict:
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_skill_templates.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kernel.skill_templates'`

- [ ] **Step 3: Create SkillTemplate base class**

```python
# kernel/skill_templates/__init__.py
"""Skill templates — built-in template classes for Skills."""
```

```python
# kernel/skill_templates/base.py
"""Base class for all skill templates."""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillTemplate(ABC):
    """Base class for skill templates.

    Provides data persistence and a standard interface for skill execution.
    Each skill instance gets isolated storage at data_dir/skills/{skill_name}/.
    """

    def __init__(self, skill_name: str, data_dir: Path) -> None:
        self.skill_name = skill_name
        self._data_path = data_dir / "skills" / skill_name
        self._data_path.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def template_name(self) -> str:
        """Return template identifier (e.g., 'tracker', 'monitor')."""

    @abstractmethod
    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a skill action with given config."""

    async def save_data(self, filename: str, data: Any) -> None:
        """Save JSON data to skill's storage directory."""
        path = self._data_path / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    async def load_data(self, filename: str, default: Any = None) -> Any:
        """Load JSON data from skill's storage directory."""
        path = self._data_path / filename
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", path, e)
            return default
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_skill_templates.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/skill_templates/ tests/test_skill_templates.py
git commit -m "feat: add SkillTemplate base class with isolated storage"
```

---

## Chunk 3: Tracker Template

### Task 3: Implement tracker template

**Files:**
- Create: `kernel/skill_templates/tracker.py`
- Test: `tests/test_skill_templates.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_skill_templates.py`:

```python
from kernel.skill_templates.tracker import TrackerTemplate
from datetime import date


class TestTrackerTemplate:
    @pytest.fixture
    def tracker(self, tmp_path):
        return TrackerTemplate(skill_name="water", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {
            "unit": "мл",
            "daily_goal": 2000,
        }

    @pytest.mark.asyncio
    async def test_log_value(self, tracker, config):
        """Logging a value stores it."""
        result = await tracker.execute("log", {"amount": 250}, config)
        assert result["status"] == "logged"
        assert result["today_total"] == 250

    @pytest.mark.asyncio
    async def test_log_accumulates(self, tracker, config):
        """Multiple logs accumulate within the day."""
        await tracker.execute("log", {"amount": 250}, config)
        result = await tracker.execute("log", {"amount": 300}, config)
        assert result["today_total"] == 550

    @pytest.mark.asyncio
    async def test_summary_with_goal(self, tracker, config):
        """Summary shows progress toward daily goal."""
        await tracker.execute("log", {"amount": 1500}, config)
        result = await tracker.execute("summary", {}, config)
        assert result["today_total"] == 1500
        assert result["daily_goal"] == 2000
        assert result["remaining"] == 500
        assert result["progress_pct"] == 75.0

    @pytest.mark.asyncio
    async def test_summary_empty_day(self, tracker, config):
        """Summary on empty day shows zero."""
        result = await tracker.execute("summary", {}, config)
        assert result["today_total"] == 0
        assert result["remaining"] == 2000

    @pytest.mark.asyncio
    async def test_trend_returns_direction(self, tracker, config):
        """Trend shows direction based on recent data."""
        result = await tracker.execute("trend", {}, config)
        assert "direction" in result
        assert result["direction"] in ("up", "down", "flat", "insufficient_data")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_skill_templates.py::TestTrackerTemplate -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kernel.skill_templates.tracker'`

- [ ] **Step 3: Implement TrackerTemplate**

```python
# kernel/skill_templates/tracker.py
"""Tracker template — track numeric values over time with daily goals."""

import logging
from datetime import date, timedelta
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)


class TrackerTemplate(SkillTemplate):
    """Track a numeric value over time with optional daily goal."""

    @property
    def template_name(self) -> str:
        return "tracker"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle tracker actions: log, summary, trend."""
        if action == "log":
            return await self._log(args, config)
        if action == "summary":
            return await self._summary(config)
        if action == "trend":
            return await self._trend(config)
        return {"error": f"Unknown action: {action}"}

    async def _log(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Log a value for today."""
        amount = args.get("amount", 0)
        today = date.today().isoformat()
        unit = config.get("unit", "")

        history = await self.load_data("history.json", default={})
        day_entries = history.get(today, [])
        day_entries.append({"amount": amount})
        history[today] = day_entries
        await self.save_data("history.json", history)

        today_total = sum(e["amount"] for e in day_entries)
        return {
            "status": "logged",
            "amount": amount,
            "unit": unit,
            "today_total": today_total,
        }

    async def _summary(self, config: dict[str, Any]) -> dict[str, Any]:
        """Get summary for today."""
        today = date.today().isoformat()
        unit = config.get("unit", "")
        daily_goal = config.get("daily_goal", 0)

        history = await self.load_data("history.json", default={})
        day_entries = history.get(today, [])
        today_total = sum(e["amount"] for e in day_entries)

        remaining = max(0, daily_goal - today_total) if daily_goal else 0
        progress_pct = round(today_total / daily_goal * 100, 1) if daily_goal else 0

        return {
            "today_total": today_total,
            "unit": unit,
            "daily_goal": daily_goal,
            "remaining": remaining,
            "progress_pct": progress_pct,
            "entries_count": len(day_entries),
        }

    async def _trend(self, config: dict[str, Any]) -> dict[str, Any]:
        """Compute trend over recent days."""
        history = await self.load_data("history.json", default={})

        today = date.today()
        recent_7 = []
        recent_14 = []

        for i in range(14):
            day = (today - timedelta(days=i)).isoformat()
            total = sum(e["amount"] for e in history.get(day, []))
            if i < 7:
                recent_7.append(total)
            recent_14.append(total)

        if len([v for v in recent_14 if v > 0]) < 3:
            return {"direction": "insufficient_data", "days_tracked": len(history)}

        avg_7 = sum(recent_7) / max(len(recent_7), 1)
        avg_14 = sum(recent_14) / max(len(recent_14), 1)

        if avg_14 == 0:
            direction = "flat"
        elif avg_7 > avg_14 * 1.1:
            direction = "up"
        elif avg_7 < avg_14 * 0.9:
            direction = "down"
        else:
            direction = "flat"

        return {
            "direction": direction,
            "avg_7d": round(avg_7, 1),
            "avg_14d": round(avg_14, 1),
            "unit": config.get("unit", ""),
            "days_tracked": len(history),
        }
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_skill_templates.py::TestTrackerTemplate -v
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/skill_templates/tracker.py tests/test_skill_templates.py
git commit -m "feat: add tracker skill template (log, summary, trend)"
```

---

## Chunk 4: Remaining Templates

### Task 4: Implement reminder template

**Files:**
- Create: `kernel/skill_templates/reminder.py`
- Test: `tests/test_skill_templates.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_skill_templates.py`:

```python
from kernel.skill_templates.reminder import ReminderTemplate


class TestReminderTemplate:
    @pytest.fixture
    def reminder(self, tmp_path):
        return ReminderTemplate(skill_name="water-remind", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {
            "message": "Время выпить воды!",
            "interval_hours": 2,
            "start_hour": 8,
            "end_hour": 22,
        }

    @pytest.mark.asyncio
    async def test_check_returns_reminder(self, reminder, config):
        """Check action returns the reminder message."""
        result = await reminder.execute("check", {}, config)
        assert "message" in result
        assert result["message"] == "Время выпить воды!"

    @pytest.mark.asyncio
    async def test_snooze_records_snooze(self, reminder, config):
        """Snooze action records the snooze."""
        result = await reminder.execute("snooze", {"minutes": 30}, config)
        assert result["status"] == "snoozed"

    @pytest.mark.asyncio
    async def test_history_tracks_deliveries(self, reminder, config):
        """History shows past reminder deliveries."""
        await reminder.execute("check", {}, config)
        result = await reminder.execute("history", {}, config)
        assert isinstance(result["entries"], list)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_skill_templates.py::TestReminderTemplate -v
```

Expected: FAIL

- [ ] **Step 3: Implement ReminderTemplate**

```python
# kernel/skill_templates/reminder.py
"""Reminder template — time-based reminders with snooze."""

import logging
from datetime import datetime, timedelta
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)


class ReminderTemplate(SkillTemplate):
    """Send reminders on schedule with optional snooze."""

    @property
    def template_name(self) -> str:
        return "reminder"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle reminder actions: check, snooze, history."""
        if action == "check":
            return await self._check(config)
        if action == "snooze":
            return await self._snooze(args, config)
        if action == "history":
            return await self._history()
        return {"error": f"Unknown action: {action}"}

    async def _check(self, config: dict[str, Any]) -> dict[str, Any]:
        """Check if reminder should fire now."""
        now = datetime.now()
        start_hour = config.get("start_hour", 8)
        end_hour = config.get("end_hour", 22)
        message = config.get("message", "Reminder!")

        snooze_data = await self.load_data("snooze.json", default={})
        snooze_until = snooze_data.get("until")
        if snooze_until and datetime.fromisoformat(snooze_until) > now:
            return {"should_fire": False, "reason": "snoozed", "message": message}

        if not (start_hour <= now.hour < end_hour):
            return {"should_fire": False, "reason": "outside_hours", "message": message}

        # Record delivery
        history = await self.load_data("history.json", default=[])
        history.append({"time": now.isoformat(), "message": message})
        history = history[-100:]  # keep last 100
        await self.save_data("history.json", history)

        return {"should_fire": True, "message": message}

    async def _snooze(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Snooze reminder for N minutes."""
        minutes = args.get("minutes", 30)
        until = datetime.now() + timedelta(minutes=minutes)
        await self.save_data("snooze.json", {"until": until.isoformat()})
        return {"status": "snoozed", "until": until.isoformat(), "minutes": minutes}

    async def _history(self) -> dict[str, Any]:
        """Return reminder delivery history."""
        history = await self.load_data("history.json", default=[])
        return {"entries": history, "total": len(history)}
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_skill_templates.py::TestReminderTemplate -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/skill_templates/reminder.py tests/test_skill_templates.py
git commit -m "feat: add reminder skill template (check, snooze, history)"
```

### Task 5: Implement monitor template

**Files:**
- Create: `kernel/skill_templates/monitor.py`
- Test: `tests/test_skill_templates.py`

- [ ] **Step 1: Write failing tests**

```python
from kernel.skill_templates.monitor import MonitorTemplate


class TestMonitorTemplate:
    @pytest.fixture
    def monitor(self, tmp_path):
        return MonitorTemplate(skill_name="site-mon", data_dir=tmp_path)

    @pytest.fixture
    def config(self):
        return {
            "url": "https://httpbin.org/status/200",
            "expected_status": 200,
            "alert_on_failure": True,
        }

    @pytest.mark.asyncio
    async def test_check_returns_status(self, monitor, config):
        """Check returns status info (mocked)."""
        result = await monitor.execute(
            "check", {"_mock_status": 200}, config,
        )
        assert result["status_code"] == 200
        assert result["is_ok"] is True

    @pytest.mark.asyncio
    async def test_check_failure_flagged(self, monitor, config):
        """Failed check is flagged."""
        result = await monitor.execute(
            "check", {"_mock_status": 500}, config,
        )
        assert result["is_ok"] is False

    @pytest.mark.asyncio
    async def test_get_history(self, monitor, config):
        """History accumulates checks."""
        await monitor.execute("check", {"_mock_status": 200}, config)
        await monitor.execute("check", {"_mock_status": 500}, config)
        result = await monitor.execute("history", {}, config)
        assert result["total"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_skill_templates.py::TestMonitorTemplate -v
```

- [ ] **Step 3: Implement MonitorTemplate**

```python
# kernel/skill_templates/monitor.py
"""Monitor template — periodic URL/API checks with alerts."""

import logging
from datetime import datetime
from typing import Any

from kernel.skill_templates.base import SkillTemplate

logger = logging.getLogger(__name__)


class MonitorTemplate(SkillTemplate):
    """Periodically check a URL and alert on failure."""

    @property
    def template_name(self) -> str:
        return "monitor"

    async def execute(
        self, action: str, args: dict[str, Any], config: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle monitor actions: check, history."""
        if action == "check":
            return await self._check(args, config)
        if action == "history":
            return await self._history()
        return {"error": f"Unknown action: {action}"}

    async def _check(self, args: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Check URL status."""
        url = config.get("url", "")
        expected = config.get("expected_status", 200)

        # Support mock for testing
        mock_status = args.get("_mock_status")
        if mock_status is not None:
            status_code = mock_status
        else:
            try:
                import urllib.request
                req = urllib.request.Request(url, method="HEAD")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status_code = resp.status
            except Exception as e:
                status_code = 0
                logger.warning("Monitor check failed for %s: %s", url, e)

        is_ok = status_code == expected
        entry = {
            "time": datetime.now().isoformat(),
            "status_code": status_code,
            "is_ok": is_ok,
            "url": url,
        }

        # Save to history
        history = await self.load_data("history.json", default=[])
        history.append(entry)
        history = history[-100:]
        await self.save_data("history.json", history)

        return {
            "status_code": status_code,
            "is_ok": is_ok,
            "url": url,
            "expected_status": expected,
        }

    async def _history(self) -> dict[str, Any]:
        """Return check history."""
        history = await self.load_data("history.json", default=[])
        ok_count = sum(1 for h in history if h.get("is_ok"))
        return {
            "entries": history[-20:],
            "total": len(history),
            "ok_count": ok_count,
            "fail_count": len(history) - ok_count,
        }
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_skill_templates.py::TestMonitorTemplate -v
```

Expected: 3 PASS

- [ ] **Step 5: Implement notifier + logger templates (same pattern)**

Create `kernel/skill_templates/notifier.py`:
- Actions: `notify(message, channel)`, `log()`, `history()`
- Channels: voice, telegram, dashboard (via event bus topic)
- Stores notification history

Create `kernel/skill_templates/logger.py`:
- Actions: `log(event, note)`, `search(query)`, `history(count)`
- Stores timestamped entries
- Simple substring search

- [ ] **Step 6: Run all template tests**

```bash
uv run pytest tests/test_skill_templates.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add kernel/skill_templates/ tests/test_skill_templates.py
git commit -m "feat: add monitor, notifier, logger skill templates"
```

---

## Chunk 5: SkillExecutor & Dynamic Scheduler

### Task 6: Create SkillExecutor

**Files:**
- Create: `kernel/skill_executor.py`
- Test: `tests/test_skill_executor.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_skill_executor.py`:

```python
import yaml
from pathlib import Path
from kernel.skill_executor import SkillExecutor


@pytest.fixture
def skills_dir(tmp_path):
    """Create a test skill directory with manifest + skill.yaml."""
    skill_dir = tmp_path / "agents" / "water-tracker"
    skill_dir.mkdir(parents=True)

    manifest = {
        "name": "water-tracker",
        "version": "1.0.0",
        "description": "Track water intake",
        "protocol": "skill",
        "tools": [
            {"name": "log", "description": "Log intake", "parameters": {"amount": {"type": "number"}}},
            {"name": "summary", "description": "Daily summary", "parameters": {}},
        ],
        "permissions": ["storage", "notifications"],
    }
    (skill_dir / "manifest.yaml").write_text(yaml.dump(manifest))

    skill_config = {
        "template": "tracker",
        "display_name": "Трекер воды",
        "config": {
            "unit": "мл",
            "daily_goal": 2000,
        },
    }
    (skill_dir / "skill.yaml").write_text(yaml.dump(skill_config))

    return tmp_path


class TestSkillExecutor:
    @pytest.fixture
    def executor(self, skills_dir):
        return SkillExecutor(data_dir=skills_dir / "data")

    @pytest.mark.asyncio
    async def test_load_skill(self, executor, skills_dir):
        """Executor loads skill from directory."""
        executor.load_skill(skills_dir / "agents" / "water-tracker")
        assert "water-tracker" in executor.list_skills()

    @pytest.mark.asyncio
    async def test_execute_skill_action(self, executor, skills_dir):
        """Executor runs action on loaded skill."""
        executor.load_skill(skills_dir / "agents" / "water-tracker")
        result = await executor.execute("water-tracker", "log", {"amount": 500})
        assert result["status"] == "logged"
        assert result["today_total"] == 500

    @pytest.mark.asyncio
    async def test_execute_unknown_skill_raises(self, executor):
        """Executing unknown skill raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            await executor.execute("nonexistent", "log", {})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_skill_executor.py::TestSkillExecutor -v
```

Expected: FAIL

- [ ] **Step 3: Implement SkillExecutor**

```python
# kernel/skill_executor.py
"""Skill executor — runs skill templates in-process from YAML config."""

import logging
from pathlib import Path
from typing import Any

import yaml

from kernel.skill_templates.base import SkillTemplate
from kernel.skill_templates.tracker import TrackerTemplate
from kernel.skill_templates.reminder import ReminderTemplate
from kernel.skill_templates.monitor import MonitorTemplate
from kernel.skill_templates.notifier import NotifierTemplate
from kernel.skill_templates.logger import LoggerTemplate

logger = logging.getLogger(__name__)

TEMPLATE_REGISTRY: dict[str, type[SkillTemplate]] = {
    "tracker": TrackerTemplate,
    "reminder": ReminderTemplate,
    "monitor": MonitorTemplate,
    "notifier": NotifierTemplate,
    "logger": LoggerTemplate,
}


class SkillExecutor:
    """Loads and executes skills in-process using template classes.

    No subprocess, no sandbox — skills are trusted YAML configs
    running through built-in templates.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._skills: dict[str, dict[str, Any]] = {}
        # {name: {"template": SkillTemplate, "config": dict, "skill_yaml": dict}}

    def load_skill(self, skill_dir: Path) -> None:
        """Load skill from directory containing manifest.yaml + skill.yaml."""
        skill_yaml_path = skill_dir / "skill.yaml"
        if not skill_yaml_path.exists():
            raise FileNotFoundError(f"No skill.yaml in {skill_dir}")

        with open(skill_yaml_path) as f:
            skill_yaml = yaml.safe_load(f)

        template_name = skill_yaml.get("template")
        if template_name not in TEMPLATE_REGISTRY:
            raise ValueError(
                f"Unknown template '{template_name}'. "
                f"Available: {list(TEMPLATE_REGISTRY.keys())}"
            )

        name = skill_dir.name
        template_cls = TEMPLATE_REGISTRY[template_name]
        template = template_cls(skill_name=name, data_dir=self._data_dir)

        self._skills[name] = {
            "template": template,
            "config": skill_yaml.get("config", {}),
            "skill_yaml": skill_yaml,
        }
        logger.info("Loaded skill: %s (template: %s)", name, template_name)

    async def execute(
        self, skill_name: str, action: str, args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a skill action."""
        if skill_name not in self._skills:
            raise ValueError(f"Skill '{skill_name}' not found")

        skill = self._skills[skill_name]
        template: SkillTemplate = skill["template"]
        config = skill["config"]
        return await template.execute(action, args or {}, config)

    def list_skills(self) -> list[str]:
        """List loaded skill names."""
        return list(self._skills.keys())

    def get_skill_info(self, name: str) -> dict[str, Any] | None:
        """Get skill config and template info."""
        skill = self._skills.get(name)
        if not skill:
            return None
        return {
            "name": name,
            "template": skill["template"].template_name,
            "config": skill["config"],
            "display_name": skill["skill_yaml"].get("display_name", name),
        }

    def unload_skill(self, name: str) -> bool:
        """Unload a skill."""
        return self._skills.pop(name, None) is not None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_skill_executor.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add kernel/skill_executor.py tests/test_skill_executor.py
git commit -m "feat: add SkillExecutor — in-process skill runner"
```

### Task 7: Extend Scheduler with dynamic cron

**Files:**
- Modify: `kernel/scheduler.py`
- Modify: `pyproject.toml`
- Test: `tests/test_scheduler_dynamic.py`

- [ ] **Step 1: Add croniter dependency**

```bash
cd C:\Users\User\Desktop\Jarvis
uv add croniter
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_scheduler_dynamic.py
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
        s = Scheduler(bus, config)
        return s

    def test_register_cron(self, scheduler):
        """Can register a dynamic cron job."""
        scheduler.register_cron("water-reminder", "0 */2 * * *")
        assert "water-reminder" in scheduler.list_cron_jobs()

    def test_unregister_cron(self, scheduler):
        """Can unregister a cron job."""
        scheduler.register_cron("test", "0 * * * *")
        scheduler.unregister_cron("test")
        assert "test" not in scheduler.list_cron_jobs()

    def test_next_run_calculated(self, scheduler):
        """Registration calculates next run time."""
        scheduler.register_cron("test", "0 9 * * *")
        jobs = scheduler.list_cron_jobs()
        assert jobs["test"]["next_run"] is not None

    def test_invalid_cron_raises(self, scheduler):
        """Invalid cron expression raises ValueError."""
        with pytest.raises(ValueError, match="Invalid cron"):
            scheduler.register_cron("bad", "not a cron")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_scheduler_dynamic.py -v
```

Expected: FAIL — `register_cron` not found

- [ ] **Step 4: Add dynamic cron methods to Scheduler**

Add to `kernel/scheduler.py`:

```python
from croniter import croniter

# Add to __init__:
self._cron_jobs: dict[str, dict[str, Any]] = {}
# {name: {"cron": str, "next_run": datetime, "callback": str}}

def register_cron(self, name: str, cron_expr: str, topic: str | None = None) -> None:
    """Register a dynamic cron job."""
    if not croniter.is_valid(cron_expr):
        raise ValueError(f"Invalid cron expression: {cron_expr}")
    now = datetime.now()
    cron = croniter(cron_expr, now)
    next_run = cron.get_next(datetime)
    self._cron_jobs[name] = {
        "cron": cron_expr,
        "next_run": next_run,
        "topic": topic or f"skill.{name}.trigger",
    }
    logger.info("Registered cron '%s': %s (next: %s)", name, cron_expr, next_run)

def unregister_cron(self, name: str) -> None:
    """Remove a dynamic cron job."""
    self._cron_jobs.pop(name, None)

def list_cron_jobs(self) -> dict[str, dict[str, Any]]:
    """List all dynamic cron jobs."""
    return {
        name: {"cron": j["cron"], "next_run": j["next_run"].isoformat(), "topic": j["topic"]}
        for name, j in self._cron_jobs.items()
    }
```

Add to `_loop()` (inside the try block, after hourly check):

```python
# Dynamic cron jobs
now = self._now()
for name, job in list(self._cron_jobs.items()):
    if now >= job["next_run"]:
        await self.emit(job["topic"])
        # Recalculate next run
        cron = croniter(job["cron"], now)
        job["next_run"] = cron.get_next(datetime)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_scheduler_dynamic.py -v
```

Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add kernel/scheduler.py tests/test_scheduler_dynamic.py pyproject.toml
git commit -m "feat: dynamic cron registration in Scheduler"
```

---

## Chunk 6: FastAPI Integration

### Task 8: Wire SkillExecutor into kernel

**Files:**
- Modify: `kernel/main.py`
- Modify: `kernel/plugin_registry.py`

- [ ] **Step 1: Update PluginRegistry to flag skills**

In `kernel/plugin_registry.py`, after `discover()` method, add filtering:

```python
def list_skills(self) -> list[AgentManifest]:
    """Return only manifests with protocol='skill'."""
    return [m for m in self._manifests.values() if m.protocol == "skill"]

def list_agents(self) -> list[AgentManifest]:
    """Return only manifests with protocol!='skill'."""
    return [m for m in self._manifests.values() if m.protocol != "skill"]
```

- [ ] **Step 2: Add SkillExecutor init to main.py**

In `kernel/main.py`, in the lifespan/startup:

```python
from kernel.skill_executor import SkillExecutor

# After plugin_registry.discover():
skill_executor = SkillExecutor(data_dir=Path("data"))
for manifest in plugin_registry.list_skills():
    skill_dir = Path("agents") / manifest.name
    try:
        skill_executor.load_skill(skill_dir)
    except Exception as e:
        logger.warning("Failed to load skill %s: %s", manifest.name, e)
app.state.skill_executor = skill_executor
```

- [ ] **Step 3: Add skill API routes**

```python
@app.get("/skills")
async def list_skills(request: Request):
    executor = request.app.state.skill_executor
    return [executor.get_skill_info(name) for name in executor.list_skills()]

@app.post("/skills/{name}/{action}")
async def execute_skill(name: str, action: str, request: Request):
    body = await request.json() if request.content_length else {}
    try:
        result = await request.app.state.skill_executor.execute(name, action, body)
        return result
    except ValueError as e:
        return {"error": str(e)}, 404
```

- [ ] **Step 4: Register skill schedules with Scheduler**

```python
# After skill loading, register cron jobs:
for name in skill_executor.list_skills():
    info = skill_executor.get_skill_info(name)
    config = info["config"] if info else {}
    cron = config.get("schedule", {}).get("cron")
    interval_h = config.get("reminders", {}).get("interval_hours")
    if cron:
        scheduler.register_cron(name, cron)
    elif interval_h:
        scheduler.register_cron(name, f"0 */{interval_h} * * *")
```

- [ ] **Step 5: Manual integration test**

```bash
# Start kernel
uv run python -m kernel.main

# In another terminal:
curl http://localhost:3005/skills
curl -X POST http://localhost:3005/skills/water-tracker/log \
  -H "Content-Type: application/json" \
  -d '{"amount": 250}'
curl -X POST http://localhost:3005/skills/water-tracker/summary \
  -H "Content-Type: application/json"
```

- [ ] **Step 6: Commit**

```bash
git add kernel/main.py kernel/plugin_registry.py
git commit -m "feat: wire SkillExecutor into kernel with API routes"
```

---

## Chunk 7: Example Skill & Smoke Test

### Task 9: Create example water-tracker skill

**Files:**
- Create: `agents/water-tracker/manifest.yaml`
- Create: `agents/water-tracker/skill.yaml`

- [ ] **Step 1: Create manifest**

```yaml
# agents/water-tracker/manifest.yaml
name: water-tracker
version: "1.0.0"
description: "Tracks daily water intake with reminders every 2 hours"
protocol: skill
capabilities:
  - tracker
tools:
  - name: log
    description: "Log water intake"
    parameters:
      amount:
        type: number
        description: "Amount in ml"
  - name: summary
    description: "Get daily summary"
    parameters: {}
  - name: trend
    description: "Get weekly trend"
    parameters: {}
scheduled_events: []
permissions:
  - storage
  - notifications
```

- [ ] **Step 2: Create skill config**

```yaml
# agents/water-tracker/skill.yaml
template: tracker
display_name: "Трекер воды"
config:
  unit: "мл"
  daily_goal: 2000
  reminders:
    enabled: true
    interval_hours: 2
    start_hour: 8
    end_hour: 22
    message: "Время выпить воды!"
  tracking:
    daily_summary: true
    weekly_chart: true
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/test_skill_executor.py tests/test_skill_templates.py tests/test_scheduler_dynamic.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add agents/water-tracker/ tests/
git commit -m "feat: add water-tracker example skill + full test suite"
```

---

## Summary

| Chunk | Tasks | Files Created | Files Modified |
|-------|-------|--------------|----------------|
| 1: Models | 1 | 0 | 2 (models.py, runtime.py) |
| 2: Base template | 2 | 2 | 0 |
| 3: Tracker | 3 | 1 | 1 (tests) |
| 4: Other templates | 4-5 | 4 | 1 (tests) |
| 5: Executor + Scheduler | 6-7 | 2 | 2 (scheduler, pyproject) |
| 6: FastAPI wiring | 8 | 0 | 2 (main, plugin_registry) |
| 7: Example + smoke | 9 | 2 | 0 |

**Total: 9 tasks, ~11 new files, ~6 modified files**
**Estimated time: 2-3 hours**
