"""Tests for tasks agent."""

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
    return json.loads(proc.stdout.readline().strip())


@pytest.fixture
def agent_proc(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "agents/tasks/agent.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path.cwd()),
        env={**os.environ, "KALI_DATA_DIR": str(tmp_path)},
    )
    yield proc
    proc.terminate()
    proc.wait()


class TestTasksAgent:
    def test_add_and_list_tasks(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        send_rpc(
            agent_proc,
            "execute",
            {"action": "add_task", "args": {"title": "Buy milk"}},
            id=2,
        )
        resp = send_rpc(agent_proc, "execute", {"action": "list_tasks", "args": {}}, id=3)
        assert len(resp["result"]["tasks"]) == 1
        assert resp["result"]["tasks"][0]["title"] == "Buy milk"

    def test_complete_task(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        add_resp = send_rpc(
            agent_proc,
            "execute",
            {"action": "add_task", "args": {"title": "Test task"}},
            id=2,
        )
        task_id = add_resp["result"]["task"]["id"]
        send_rpc(
            agent_proc,
            "execute",
            {"action": "complete_task", "args": {"task_id": task_id}},
            id=3,
        )
        resp = send_rpc(agent_proc, "execute", {"action": "list_tasks", "args": {}}, id=4)
        assert resp["result"]["tasks"][0]["completed"] is True

    def test_get_summary(self, agent_proc) -> None:
        send_rpc(agent_proc, "initialize", {"config": {}})
        send_rpc(agent_proc, "execute", {"action": "add_task", "args": {"title": "T1"}}, id=2)
        send_rpc(agent_proc, "execute", {"action": "add_task", "args": {"title": "T2"}}, id=3)
        resp = send_rpc(agent_proc, "execute", {"action": "get_summary", "args": {}}, id=4)
        assert resp["result"]["total"] == 2
        assert resp["result"]["done"] == 0
