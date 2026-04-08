"""Tests for LLM Router."""

from unittest.mock import AsyncMock, patch

import pytest

from kernel.llm_router import LLMRequest, LLMResponse, LLMRouter
from kernel.models import LLMConfig


@pytest.fixture
def config() -> LLMConfig:
    return LLMConfig()


@pytest.fixture
def router(config: LLMConfig) -> LLMRouter:
    return LLMRouter(config)


class TestLLMRequest:
    def test_create_request(self) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[])
        assert req.text == "hello"
        assert req.force_provider is None

    def test_force_provider(self) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[], force_provider="cloud")
        assert req.force_provider == "cloud"


class TestLLMResponse:
    def test_create_response(self) -> None:
        resp = LLMResponse(text="Hi there!", tool_calls=None, provider_used="local", latency_ms=50)
        assert resp.text == "Hi there!"
        assert resp.tool_calls is None
        assert resp.provider_used == "local"


class TestLLMRouter:
    def test_create_router(self, router: LLMRouter) -> None:
        assert router.config.cloud_provider == "anthropic"
        assert router.config.local_provider == "ollama"

    def test_should_use_cloud_with_tools(self, router: LLMRouter) -> None:
        tools = [{"type": "function", "function": {"name": "test", "description": "test"}}]
        req = LLMRequest(text="schedule meeting", context=[], available_tools=tools)
        provider = router.select_provider(req)
        assert provider == "cloud"

    def test_should_use_local_without_tools(self, router: LLMRouter) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[])
        provider = router.select_provider(req)
        assert provider == "local"

    def test_force_provider_overrides(self, router: LLMRouter) -> None:
        tools = [{"type": "function", "function": {"name": "test", "description": "test"}}]
        req = LLMRequest(text="test", context=[], available_tools=tools, force_provider="local")
        provider = router.select_provider(req)
        assert provider == "local"

    async def test_route_returns_response(self, router: LLMRouter) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[])
        with patch.object(router, "_call_local", new_callable=AsyncMock) as mock_local:
            mock_local.return_value = LLMResponse(
                text="Hi!", tool_calls=None, provider_used="local", latency_ms=10
            )
            resp = await router.route(req)
            assert resp.text == "Hi!"
            assert resp.provider_used == "local"
