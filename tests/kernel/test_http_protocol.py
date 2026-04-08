"""Tests for HTTP protocol client."""

from kernel.agent_runtime.protocols.http_client import HttpProtocol


class TestHttpProtocol:
    def test_create_protocol(self) -> None:
        proto = HttpProtocol(agent_name="smart-home", base_url="http://localhost:8080")
        assert proto.agent_name == "smart-home"
        assert proto.base_url == "http://localhost:8080"
        assert not proto.is_running

    def test_default_timeout(self) -> None:
        proto = HttpProtocol(agent_name="test", base_url="http://localhost:8080")
        assert proto.timeout == 30.0

    async def test_start_sets_running(self) -> None:
        proto = HttpProtocol(agent_name="test", base_url="http://localhost:8080")
        await proto.start()
        assert proto.is_running
        await proto.stop()
        assert not proto.is_running
