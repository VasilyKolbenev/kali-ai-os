"""Tests for calendar agent."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest


def send_rpc(proc, method, params=None, id=1):
    """Send JSON-RPC to agent subprocess and get response."""
    request = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": id}
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline().strip())


@pytest.fixture
def agent_proc(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "agents/calendar/agent.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path.cwd()),
        env={**os.environ, "JARVIS_DATA_DIR": str(tmp_path)},
    )
    yield proc
    proc.terminate()
    proc.wait()


class TestCalendarAgent:
    def test_create_and_get_events(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        send_rpc(
            agent_proc,
            "execute",
            {
                "action": "create_event",
                "args": {
                    "title": "Team call",
                    "start": "2026-04-08T10:00:00",
                    "end": "2026-04-08T11:00:00",
                },
            },
            id=2,
        )
        resp = send_rpc(
            agent_proc,
            "execute",
            {"action": "get_events", "args": {"date": "2026-04-08"}},
            id=3,
        )
        assert len(resp["result"]["events"]) == 1
        assert resp["result"]["events"][0]["title"] == "Team call"

    def test_get_events_today(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        today = datetime.now().strftime("%Y-%m-%d")
        send_rpc(
            agent_proc,
            "execute",
            {
                "action": "create_event",
                "args": {
                    "title": "Standup",
                    "start": f"{today}T09:00:00",
                    "end": f"{today}T09:30:00",
                },
            },
            id=2,
        )
        resp = send_rpc(
            agent_proc,
            "execute",
            {"action": "get_events", "args": {"date": "today"}},
            id=3,
        )
        assert len(resp["result"]["events"]) == 1
