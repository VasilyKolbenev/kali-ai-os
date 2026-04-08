# Built-in Agents Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan.

**Goal:** Build 6 built-in agents — system, tasks, calendar, life-dashboard, smart-home, coding — each as a standalone Python script using the native JSON-RPC protocol. v1 uses local storage; external API integrations come in v2.

**Architecture:** Each agent is a Python script in `agents/{name}/agent.py` with a `manifest.yaml`. They follow the same pattern as `_example/agent.py`: read JSON-RPC from stdin, process, write to stdout. A shared `agents/_base/agent_base.py` provides the boilerplate.

**Tech Stack:** Python 3.12+, JSON-RPC 2.0, json file storage (local), existing kernel

---

## File Structure

```
agents/
  _base/
    agent_base.py            # Shared base class for all native agents
  system/
    manifest.yaml
    agent.py                 # Timer, volume, system info
  tasks/
    manifest.yaml
    agent.py                 # Todo/task management (local JSON)
  calendar/
    manifest.yaml
    agent.py                 # Calendar events (local JSON)
  life-dashboard/
    manifest.yaml
    agent.py                 # Sleep, spending, energy tracking
  smart-home/
    manifest.yaml
    agent.py                 # Home automation stub (HTTP-ready)
  coding/
    manifest.yaml
    agent.py                 # Coding assistant stub
tests/
  agents/
    test_agent_base.py
    test_system_agent.py
    test_tasks_agent.py
    test_calendar_agent.py
```

---

## Chunk 1: Agent Base + System Agent

### Task 1: Shared Agent Base Class

**Files:**
- Create: `agents/_base/agent_base.py`
- Create: `tests/agents/__init__.py`
- Create: `tests/agents/test_agent_base.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for agent base class."""

import json
import pytest
from agents._base.agent_base import BaseAgent


class TestAgent(BaseAgent):
    """Test agent for testing base class."""

    def get_name(self) -> str:
        return "test"

    def handle_action(self, action: str, args: dict) -> dict:
        if action == "greet":
            return {"message": f"Hello, {args.get('name', 'World')}!"}
        raise ValueError(f"Unknown action: {action}")


class TestBaseAgent:
    def test_handle_initialize(self) -> None:
        agent = TestAgent()
        result = agent.handle_request({
            "jsonrpc": "2.0", "method": "initialize",
            "params": {"config": {}}, "id": 1,
        })
        assert result["result"]["status"] == "ok"

    def test_handle_health(self) -> None:
        agent = TestAgent()
        result = agent.handle_request({
            "jsonrpc": "2.0", "method": "health", "params": {}, "id": 2,
        })
        assert result["result"]["status"] == "healthy"
        assert "uptime_s" in result["result"]

    def test_handle_execute(self) -> None:
        agent = TestAgent()
        result = agent.handle_request({
            "jsonrpc": "2.0", "method": "execute",
            "params": {"action": "greet", "args": {"name": "Jarvis"}}, "id": 3,
        })
        assert result["result"]["message"] == "Hello, Jarvis!"

    def test_handle_unknown_method(self) -> None:
        agent = TestAgent()
        result = agent.handle_request({
            "jsonrpc": "2.0", "method": "unknown", "params": {}, "id": 4,
        })
        assert "error" in result

    def test_handle_execute_unknown_action(self) -> None:
        agent = TestAgent()
        result = agent.handle_request({
            "jsonrpc": "2.0", "method": "execute",
            "params": {"action": "nonexistent", "args": {}}, "id": 5,
        })
        assert "error" in result
```

- [ ] **Step 2: Implement base class**

```python
"""Shared base class for native JSON-RPC agents."""

import json
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseAgent(ABC):
    """Base class for all native Jarvis agents.

    Subclasses implement get_name() and handle_action().
    The base handles JSON-RPC protocol, health, init, shutdown.
    """

    def __init__(self) -> None:
        self._start_time = time.time()
        self._config: dict[str, Any] = {}
        self._data_dir = Path(f"data/agents/{self.get_name()}")
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def get_name(self) -> str:
        """Return agent name."""

    @abstractmethod
    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a tool action. Raise ValueError for unknown actions."""

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a JSON-RPC request and return response."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                self._config = params.get("config", {})
                result = {"status": "ok", "name": self.get_name()}
            elif method == "health":
                result = {
                    "status": "healthy",
                    "uptime_s": int(time.time() - self._start_time),
                    "name": self.get_name(),
                }
            elif method == "execute":
                action = params.get("action", "")
                args = params.get("args", {})
                result = self.handle_action(action, args)
            elif method == "shutdown":
                result = {"status": "ok"}
                response = {"jsonrpc": "2.0", "result": result, "id": request_id}
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                sys.exit(0)
            else:
                return {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                    "id": request_id,
                }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": str(e)},
                "id": request_id,
            }

        return {"jsonrpc": "2.0", "result": result, "id": request_id}

    def _load_json(self, filename: str) -> Any:
        """Load data from a JSON file in the agent's data directory."""
        path = self._data_dir / filename
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _save_json(self, filename: str, data: Any) -> None:
        """Save data to a JSON file in the agent's data directory."""
        path = self._data_dir / filename
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def run(self) -> None:
        """Main loop — read JSON-RPC from stdin."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
            except json.JSONDecodeError:
                response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: shared agent base class with JSON-RPC protocol"
```

---

### Task 2: System Agent

**Files:**
- Create: `agents/system/manifest.yaml`
- Create: `agents/system/agent.py`
- Create: `tests/agents/test_system_agent.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for system agent."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def send_rpc(proc, method, params=None, id=1):
    """Send JSON-RPC to agent subprocess and get response."""
    request = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": id}
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    return json.loads(line)


@pytest.fixture
def agent_proc():
    proc = subprocess.Popen(
        [sys.executable, "agents/system/agent.py"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(Path.cwd()),
    )
    yield proc
    proc.terminate()
    proc.wait()


class TestSystemAgent:
    def test_initialize(self, agent_proc) -> None:
        resp = send_rpc(agent_proc, "initialize", {"config": {}})
        assert resp["result"]["status"] == "ok"

    def test_health(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "health", id=2)
        assert resp["result"]["status"] == "healthy"

    def test_get_system_info(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "execute", {"action": "get_system_info", "args": {}}, id=2)
        result = resp["result"]
        assert "platform" in result
        assert "python_version" in result

    def test_get_time(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "execute", {"action": "get_time", "args": {}}, id=2)
        assert "time" in resp["result"]
        assert "date" in resp["result"]

    def test_set_timer(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "execute", {
            "action": "set_timer", "args": {"seconds": 5, "label": "test"}
        }, id=2)
        assert resp["result"]["status"] == "timer_set"
```

- [ ] **Step 2: Create manifest + agent**

`agents/system/manifest.yaml`:
```yaml
name: system
version: "1.0.0"
description: "System commands — time, timers, system info"
capabilities:
  - system.info
  - system.timer
tools:
  - name: get_time
    description: "Get current date and time"
    parameters: {}
  - name: get_system_info
    description: "Get system information (OS, CPU, memory)"
    parameters: {}
  - name: set_timer
    description: "Set a countdown timer"
    parameters:
      seconds: { type: integer, description: "Timer duration in seconds" }
      label: { type: string, description: "Timer label" }
protocol: native
permissions: []
```

`agents/system/agent.py`:
```python
"""System agent — time, timers, system information."""

import platform
import sys
import os
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class SystemAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__()
        self._timers: list[dict[str, Any]] = []

    def get_name(self) -> str:
        return "system"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "get_time":
            now = datetime.now()
            return {
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "weekday": now.strftime("%A"),
                "timezone": str(now.astimezone().tzinfo),
            }
        elif action == "get_system_info":
            import shutil
            total, used, free = shutil.disk_usage("/")
            return {
                "platform": platform.system(),
                "platform_version": platform.version(),
                "python_version": platform.python_version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "disk_free_gb": round(free / (1024**3), 1),
            }
        elif action == "set_timer":
            seconds = args.get("seconds", 60)
            label = args.get("label", "Timer")
            timer = {"seconds": seconds, "label": label, "set_at": datetime.now().isoformat()}
            self._timers.append(timer)
            return {"status": "timer_set", "label": label, "seconds": seconds}
        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    SystemAgent().run()
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: system agent with time, system info, timer"
```

---

## Chunk 2: Tasks + Calendar Agents

### Task 3: Tasks Agent

**Files:**
- Create: `agents/tasks/manifest.yaml`
- Create: `agents/tasks/agent.py`
- Create: `tests/agents/test_tasks_agent.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for tasks agent."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def send_rpc(proc, method, params=None, id=1):
    request = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": id}
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline().strip())


@pytest.fixture
def agent_proc(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    proc = subprocess.Popen(
        [sys.executable, "agents/tasks/agent.py"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(Path.cwd()),
        env={**dict(os.environ), "JARVIS_DATA_DIR": str(tmp_path)},
    )
    yield proc
    proc.terminate()
    proc.wait()


import os


class TestTasksAgent:
    def test_add_and_list_tasks(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        send_rpc(agent_proc, "execute", {
            "action": "add_task", "args": {"title": "Buy milk", "priority": "high"}
        }, id=2)
        resp = send_rpc(agent_proc, "execute", {"action": "list_tasks", "args": {}}, id=3)
        assert len(resp["result"]["tasks"]) == 1
        assert resp["result"]["tasks"][0]["title"] == "Buy milk"

    def test_complete_task(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        add_resp = send_rpc(agent_proc, "execute", {
            "action": "add_task", "args": {"title": "Test task"}
        }, id=2)
        task_id = add_resp["result"]["task"]["id"]
        send_rpc(agent_proc, "execute", {
            "action": "complete_task", "args": {"task_id": task_id}
        }, id=3)
        resp = send_rpc(agent_proc, "execute", {"action": "list_tasks", "args": {}}, id=4)
        assert resp["result"]["tasks"][0]["completed"] is True

    def test_get_summary(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        send_rpc(agent_proc, "execute", {"action": "add_task", "args": {"title": "Task 1"}}, id=2)
        send_rpc(agent_proc, "execute", {"action": "add_task", "args": {"title": "Task 2"}}, id=3)
        resp = send_rpc(agent_proc, "execute", {"action": "get_summary", "args": {}}, id=4)
        assert resp["result"]["total"] == 2
        assert resp["result"]["done"] == 0
```

- [ ] **Step 2: Create manifest + agent**

`agents/tasks/manifest.yaml`:
```yaml
name: tasks
version: "1.0.0"
description: "Task and todo management"
capabilities:
  - tasks.read
  - tasks.write
tools:
  - name: add_task
    description: "Add a new task"
    parameters:
      title: { type: string, description: "Task title" }
      priority: { type: string, description: "Priority: low, medium, high" }
  - name: list_tasks
    description: "List all tasks"
    parameters: {}
  - name: complete_task
    description: "Mark a task as complete"
    parameters:
      task_id: { type: string, description: "Task ID to complete" }
  - name: get_summary
    description: "Get task summary (total, done, pending)"
    parameters: {}
protocol: native
permissions: []
```

`agents/tasks/agent.py`:
```python
"""Tasks agent — todo and task management with local JSON storage."""

import os
import sys
import uuid
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class TasksAgent(BaseAgent):
    def __init__(self) -> None:
        data_dir = os.environ.get("JARVIS_DATA_DIR")
        if data_dir:
            import pathlib
            self._data_dir_override = pathlib.Path(data_dir) / "agents" / "tasks"
            self._data_dir_override.mkdir(parents=True, exist_ok=True)
        else:
            self._data_dir_override = None
        super().__init__()
        if self._data_dir_override:
            self._data_dir = self._data_dir_override
        self._tasks: list[dict[str, Any]] = self._load_json("tasks.json") or []

    def get_name(self) -> str:
        return "tasks"

    def _save_tasks(self) -> None:
        self._save_json("tasks.json", self._tasks)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "add_task":
            task = {
                "id": str(uuid.uuid4())[:8],
                "title": args.get("title", "Untitled"),
                "priority": args.get("priority", "medium"),
                "completed": False,
                "created_at": datetime.now().isoformat(),
            }
            self._tasks.append(task)
            self._save_tasks()
            return {"status": "added", "task": task}

        elif action == "list_tasks":
            return {"tasks": self._tasks, "count": len(self._tasks)}

        elif action == "complete_task":
            task_id = args.get("task_id", "")
            for task in self._tasks:
                if task["id"] == task_id:
                    task["completed"] = True
                    task["completed_at"] = datetime.now().isoformat()
                    self._save_tasks()
                    return {"status": "completed", "task": task}
            raise ValueError(f"Task not found: {task_id}")

        elif action == "delete_task":
            task_id = args.get("task_id", "")
            self._tasks = [t for t in self._tasks if t["id"] != task_id]
            self._save_tasks()
            return {"status": "deleted", "task_id": task_id}

        elif action == "get_summary":
            done = sum(1 for t in self._tasks if t.get("completed"))
            return {
                "total": len(self._tasks),
                "done": done,
                "pending": len(self._tasks) - done,
            }

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    TasksAgent().run()
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: tasks agent with add, list, complete, summary"
```

---

### Task 4: Calendar Agent

**Files:**
- Create: `agents/calendar/manifest.yaml`
- Create: `agents/calendar/agent.py`
- Create: `tests/agents/test_calendar_agent.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for calendar agent."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def send_rpc(proc, method, params=None, id=1):
    request = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": id}
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline().strip())


@pytest.fixture
def agent_proc(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "agents/calendar/agent.py"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(Path.cwd()),
        env={**dict(os.environ), "JARVIS_DATA_DIR": str(tmp_path)},
    )
    yield proc
    proc.terminate()
    proc.wait()


class TestCalendarAgent:
    def test_create_and_get_events(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        send_rpc(agent_proc, "execute", {
            "action": "create_event",
            "args": {"title": "Team call", "start": "2026-04-08T10:00:00", "end": "2026-04-08T11:00:00"}
        }, id=2)
        resp = send_rpc(agent_proc, "execute", {
            "action": "get_events", "args": {"date": "2026-04-08"}
        }, id=3)
        assert len(resp["result"]["events"]) == 1
        assert resp["result"]["events"][0]["title"] == "Team call"

    def test_get_events_today(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        send_rpc(agent_proc, "execute", {
            "action": "create_event",
            "args": {"title": "Daily standup", "start": f"{today}T09:00:00", "end": f"{today}T09:30:00"}
        }, id=2)
        resp = send_rpc(agent_proc, "execute", {
            "action": "get_events", "args": {"date": "today"}
        }, id=3)
        assert len(resp["result"]["events"]) == 1
```

- [ ] **Step 2: Create manifest + agent**

`agents/calendar/manifest.yaml`:
```yaml
name: calendar
version: "1.0.0"
description: "Calendar and scheduling"
capabilities:
  - calendar.read
  - calendar.write
tools:
  - name: get_events
    description: "Get calendar events for a date"
    parameters:
      date: { type: string, description: "Date in YYYY-MM-DD or 'today'" }
  - name: create_event
    description: "Create a new calendar event"
    parameters:
      title: { type: string, description: "Event title" }
      start: { type: string, description: "Start time ISO format" }
      end: { type: string, description: "End time ISO format" }
  - name: delete_event
    description: "Delete a calendar event"
    parameters:
      event_id: { type: string, description: "Event ID" }
scheduled_events:
  - "schedule.morning"
protocol: native
permissions: []
```

`agents/calendar/agent.py`:
```python
"""Calendar agent — event scheduling with local JSON storage."""

import os
import sys
import uuid
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class CalendarAgent(BaseAgent):
    def __init__(self) -> None:
        data_dir = os.environ.get("JARVIS_DATA_DIR")
        if data_dir:
            import pathlib
            self._data_dir_override = pathlib.Path(data_dir) / "agents" / "calendar"
            self._data_dir_override.mkdir(parents=True, exist_ok=True)
        else:
            self._data_dir_override = None
        super().__init__()
        if self._data_dir_override:
            self._data_dir = self._data_dir_override
        self._events: list[dict[str, Any]] = self._load_json("events.json") or []

    def get_name(self) -> str:
        return "calendar"

    def _save_events(self) -> None:
        self._save_json("events.json", self._events)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "get_events":
            date_str = args.get("date", "today")
            if date_str == "today":
                date_str = datetime.now().strftime("%Y-%m-%d")
            filtered = [e for e in self._events if e["start"].startswith(date_str)]
            return {"events": filtered, "date": date_str, "count": len(filtered)}

        elif action == "create_event":
            event = {
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
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: calendar agent with create, get, delete events"
```

---

## Chunk 3: Life Dashboard + Smart Home + Coding

### Task 5: Life Dashboard Agent

**Files:**
- Create: `agents/life-dashboard/manifest.yaml`
- Create: `agents/life-dashboard/agent.py`

- [ ] **Step 1: Create manifest + agent**

`agents/life-dashboard/manifest.yaml`:
```yaml
name: life-dashboard
version: "1.0.0"
description: "Life tracking — sleep, spending, energy, habits"
capabilities:
  - dashboard.read
  - dashboard.write
tools:
  - name: log_sleep
    description: "Log sleep data"
    parameters:
      hours: { type: number, description: "Hours slept" }
      hrv: { type: number, description: "HRV score" }
  - name: log_spending
    description: "Log a spending entry"
    parameters:
      amount: { type: number, description: "Amount spent" }
      category: { type: string, description: "Spending category" }
  - name: log_energy
    description: "Log calorie intake"
    parameters:
      calories: { type: number, description: "Calories consumed" }
  - name: get_daily_summary
    description: "Get today's life dashboard summary"
    parameters: {}
scheduled_events:
  - "schedule.morning"
  - "schedule.evening"
protocol: native
permissions: []
```

`agents/life-dashboard/agent.py`:
```python
"""Life dashboard agent — tracks sleep, spending, energy."""

import os
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class LifeDashboardAgent(BaseAgent):
    def __init__(self) -> None:
        data_dir = os.environ.get("JARVIS_DATA_DIR")
        if data_dir:
            import pathlib
            self._data_dir_override = pathlib.Path(data_dir) / "agents" / "life-dashboard"
            self._data_dir_override.mkdir(parents=True, exist_ok=True)
        else:
            self._data_dir_override = None
        super().__init__()
        if self._data_dir_override:
            self._data_dir = self._data_dir_override
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily: dict[str, Any] = self._load_json(f"{today}.json") or {
            "date": today, "sleep": None, "spending": [], "energy": [],
        }

    def get_name(self) -> str:
        return "life-dashboard"

    def _save_daily(self) -> None:
        self._save_json(f"{self._daily['date']}.json", self._daily)

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "log_sleep":
            self._daily["sleep"] = {
                "hours": args.get("hours", 0),
                "hrv": args.get("hrv", 0),
                "logged_at": datetime.now().isoformat(),
            }
            self._save_daily()
            return {"status": "logged", "sleep": self._daily["sleep"]}

        elif action == "log_spending":
            entry = {
                "amount": args.get("amount", 0),
                "category": args.get("category", "other"),
                "logged_at": datetime.now().isoformat(),
            }
            self._daily.setdefault("spending", []).append(entry)
            self._save_daily()
            total = sum(e["amount"] for e in self._daily["spending"])
            return {"status": "logged", "entry": entry, "daily_total": total}

        elif action == "log_energy":
            entry = {
                "calories": args.get("calories", 0),
                "logged_at": datetime.now().isoformat(),
            }
            self._daily.setdefault("energy", []).append(entry)
            self._save_daily()
            total = sum(e["calories"] for e in self._daily["energy"])
            return {"status": "logged", "entry": entry, "daily_total": total}

        elif action == "get_daily_summary":
            sleep = self._daily.get("sleep")
            spending = self._daily.get("spending", [])
            energy = self._daily.get("energy", [])
            return {
                "date": self._daily["date"],
                "sleep_hours": sleep["hours"] if sleep else None,
                "sleep_hrv": sleep["hrv"] if sleep else None,
                "total_spending": sum(e["amount"] for e in spending),
                "total_calories": sum(e["calories"] for e in energy),
                "spending_count": len(spending),
                "energy_count": len(energy),
            }

        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    LifeDashboardAgent().run()
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: life-dashboard agent with sleep, spending, energy tracking"
```

---

### Task 6: Smart Home + Coding Agent Stubs

**Files:**
- Create: `agents/smart-home/manifest.yaml`
- Create: `agents/smart-home/agent.py`
- Create: `agents/coding/manifest.yaml`
- Create: `agents/coding/agent.py`

- [ ] **Step 1: Create smart-home stub**

`agents/smart-home/manifest.yaml`:
```yaml
name: smart-home
version: "1.0.0"
description: "Home automation via Home Assistant"
capabilities:
  - smarthome.lights
  - smarthome.climate
  - smarthome.devices
tools:
  - name: get_devices
    description: "List smart home devices"
    parameters: {}
  - name: control_device
    description: "Control a smart home device"
    parameters:
      device_id: { type: string, description: "Device ID" }
      action: { type: string, description: "on, off, toggle, set" }
      value: { type: string, description: "Value for set action" }
  - name: get_status
    description: "Get status of all devices"
    parameters: {}
protocol: native
permissions:
  - network
```

`agents/smart-home/agent.py`:
```python
"""Smart home agent — Home Assistant integration stub."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class SmartHomeAgent(BaseAgent):
    """Stub — returns mock device data. Real HA integration in v2."""

    def __init__(self) -> None:
        super().__init__()
        self._devices = [
            {"id": "light.living_room", "name": "Living Room Light", "state": "off", "type": "light"},
            {"id": "light.bedroom", "name": "Bedroom Light", "state": "off", "type": "light"},
            {"id": "climate.thermostat", "name": "Thermostat", "state": "22°C", "type": "climate"},
        ]

    def get_name(self) -> str:
        return "smart-home"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "get_devices":
            return {"devices": self._devices, "count": len(self._devices)}
        elif action == "control_device":
            device_id = args.get("device_id", "")
            cmd = args.get("action", "toggle")
            for dev in self._devices:
                if dev["id"] == device_id:
                    if cmd in ("on", "off"):
                        dev["state"] = cmd
                    elif cmd == "toggle":
                        dev["state"] = "on" if dev["state"] == "off" else "off"
                    return {"status": "ok", "device": dev}
            raise ValueError(f"Device not found: {device_id}")
        elif action == "get_status":
            return {"devices": self._devices}
        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    SmartHomeAgent().run()
```

- [ ] **Step 2: Create coding agent stub**

`agents/coding/manifest.yaml`:
```yaml
name: coding
version: "1.0.0"
description: "Coding assistant — code review, generation, explanation"
capabilities:
  - coding.review
  - coding.generate
  - coding.explain
tools:
  - name: explain_code
    description: "Explain what a piece of code does"
    parameters:
      code: { type: string, description: "Code to explain" }
      language: { type: string, description: "Programming language" }
  - name: review_code
    description: "Review code for issues"
    parameters:
      code: { type: string, description: "Code to review" }
  - name: suggest_improvement
    description: "Suggest improvements for code"
    parameters:
      code: { type: string, description: "Code to improve" }
protocol: native
permissions: []
```

`agents/coding/agent.py`:
```python
"""Coding agent — code assistance stub. Real LLM integration in v2."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class CodingAgent(BaseAgent):
    """Stub — returns placeholder responses. Real Claude integration in v2."""

    def get_name(self) -> str:
        return "coding"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        code = args.get("code", "")
        language = args.get("language", "unknown")

        if action == "explain_code":
            lines = len(code.strip().split("\n")) if code else 0
            return {
                "explanation": f"This is {language} code with {lines} lines. "
                "Detailed explanation requires LLM integration (v2).",
                "language": language,
                "lines": lines,
            }
        elif action == "review_code":
            return {
                "review": "Code review requires LLM integration (v2).",
                "issues": [],
                "score": "N/A",
            }
        elif action == "suggest_improvement":
            return {
                "suggestions": ["LLM-powered suggestions coming in v2."],
                "original_lines": len(code.strip().split("\n")) if code else 0,
            }
        else:
            raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    CodingAgent().run()
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: smart-home and coding agent stubs"
```

---

### Task 7: Final Verification

- [ ] **Step 1: Run all tests**
- [ ] **Step 2: Lint**
- [ ] **Step 3: Verify all agents load through kernel**

```bash
curl -s http://localhost:8001/agents | python -m json.tool
```

Should show all 7 agents (example + 6 new).

- [ ] **Step 4: Commit any fixes**

---

## Summary

6 built-in agents implemented:
1. **system** — time, system info, timers
2. **tasks** — add, list, complete, delete tasks (local JSON)
3. **calendar** — create, get, delete events (local JSON)
4. **life-dashboard** — sleep, spending, energy tracking (daily JSON)
5. **smart-home** — device list, control (mock data, HA integration v2)
6. **coding** — code explain, review, suggest (stub, Claude integration v2)
