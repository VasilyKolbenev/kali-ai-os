"""Tests for system agent."""

import json
import os
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
def agent_proc(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "agents/system/agent.py"],
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


class TestSystemAgent:
    def test_initialize(self, agent_proc) -> None:
        resp = send_rpc(agent_proc, "initialize", {"config": {}})
        assert resp["result"]["status"] == "ok"

    def test_health(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "health", id=2)
        assert resp["result"]["status"] == "healthy"

    def test_get_time(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "execute", {"action": "get_time", "args": {}}, id=2)
        assert "time" in resp["result"]
        assert "date" in resp["result"]

    def test_get_system_info(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(agent_proc, "execute", {"action": "get_system_info", "args": {}}, id=2)
        result = resp["result"]
        assert "platform" in result
        assert "python_version" in result

    def test_set_timer(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        resp = send_rpc(
            agent_proc,
            "execute",
            {"action": "set_timer", "args": {"seconds": 5, "label": "test"}},
            id=2,
        )
        assert resp["result"]["status"] == "timer_set"
