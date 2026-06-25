"""Tests for native JSON-RPC protocol."""

from pathlib import Path

import pytest

from kernel.agent_runtime.protocols.native import NativeProtocol


@pytest.fixture
def example_agent_path() -> Path:
    return Path("agents/_example/agent.py")


class TestNativeProtocol:
    def test_create_protocol(self) -> None:
        proto = NativeProtocol(agent_name="test", script_path=Path("test.py"))
        assert proto.agent_name == "test"
        assert not proto.is_running

    async def test_start_and_stop(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        assert proto.is_running
        await proto.stop()
        assert not proto.is_running

    async def test_health_check(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        result = await proto.health()
        assert result["status"] == "healthy"
        await proto.stop()

    async def test_execute_tool(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        result = await proto.execute("say_hello", {"name": "World"})
        assert "Hello" in result.get("message", "")
        await proto.stop()

    async def test_initialize(self, example_agent_path: Path) -> None:
        if not example_agent_path.exists():
            pytest.skip("Example agent not found")
        proto = NativeProtocol(agent_name="example", script_path=example_agent_path)
        await proto.start()
        result = await proto.initialize({"test": True})
        assert result.get("status") == "ok"
        await proto.stop()

    async def test_execute_survives_heavy_stderr(self, tmp_path: Path) -> None:
        """A verbose-stderr agent must not deadlock.

        stderr is opened as a PIPE; if it is never drained, a user-generated
        agent that logs heavily fills the OS pipe buffer (~64 KB on Windows),
        blocks on its next stderr write, and never replies on stdout — the
        agent looks hung and execute() hits the 10 s readline timeout. The
        agent below writes 500 KB to stderr *before* its stdout reply.
        """
        script = tmp_path / "noisy_agent.py"
        script.write_text(
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    req = json.loads(line)\n"
            '    sys.stderr.write("x" * 500000)\n'
            "    sys.stderr.flush()\n"
            '    sys.stdout.write(json.dumps('
            '{"jsonrpc": "2.0", "result": {"ok": True}, "id": req.get("id")}) + "\\n")\n'
            "    sys.stdout.flush()\n",
            encoding="utf-8",
        )
        proto = NativeProtocol(agent_name="noisy", script_path=script)
        await proto.start()
        try:
            result = await proto.execute("noisy", {})
            assert result == {"ok": True}
        finally:
            await proto.stop()
