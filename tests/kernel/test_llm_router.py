"""Tests for LLM Router."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kernel.llm_router import LLMRequest, LLMResponse, LLMRouter, ToolCall
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

    @pytest.mark.xfail(
        reason="auto_route=true intentionally defaults to cloud (non-tech users rarely run a local model); local is reached via explicit selection (auto_route=false). Auto no-tools->local routing deferred until startup Ollama-availability detection exists.",
        strict=False,
    )
    def test_should_use_local_without_tools(self, router: LLMRouter) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[])
        provider = router.select_provider(req)
        assert provider == "local"

    def test_force_provider_overrides(self, router: LLMRouter) -> None:
        tools = [{"type": "function", "function": {"name": "test", "description": "test"}}]
        req = LLMRequest(text="test", context=[], available_tools=tools, force_provider="local")
        provider = router.select_provider(req)
        assert provider == "local"

    def test_explicit_local_when_auto_route_off(self) -> None:
        """Picking a local provider (auto_route disabled) must route local, not
        cloud — the privacy contract behind the provider dropdown."""
        config = LLMConfig(auto_route=False, local_provider="ollama")
        router = LLMRouter(config)
        req = LLMRequest(text="hello", context=[], available_tools=[])
        assert router.select_provider(req) == "local"

    def test_cloud_re_enabled_after_cooldown(self, router: LLMRouter) -> None:
        """One transient cloud failure must not strand the session on local
        (which strips tools) forever — cloud re-enables after the cooldown."""
        router._cloud_available = False
        router._cloud_last_fail = time.time() - 301
        tools = [{"type": "function", "function": {"name": "t", "description": "t"}}]
        req = LLMRequest(text="проверь агентов", context=[], available_tools=tools)
        assert router.select_provider(req) == "cloud"
        assert router._cloud_available is True

    def test_cloud_stays_disabled_within_cooldown(self, router: LLMRouter) -> None:
        router._cloud_available = False
        router._cloud_last_fail = time.time()
        router._local_available = True
        req = LLMRequest(text="hi", context=[], available_tools=[])
        assert router.select_provider(req) == "local"

    async def test_local_forwards_tools_and_parses_tool_calls(self) -> None:
        """Local (privacy) provider must still be able to call agents — forward
        the tool schema to Ollama and parse any tool_calls it returns."""
        config = LLMConfig(auto_route=False, local_model="llama3")
        router = LLMRouter(config)
        captured: dict = {}

        class FakeResp:
            def raise_for_status(self) -> None: ...
            def json(self) -> dict:
                return {"message": {"content": "", "tool_calls": [
                    {"function": {"name": "tasks__list_tasks", "arguments": {}}}
                ]}}

        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self
            async def __aexit__(self, *a: object) -> bool:
                return False
            async def post(self, url: str, json: dict | None = None, timeout: object = None) -> FakeResp:
                captured["json"] = json
                return FakeResp()

        tools = [{"type": "function", "function": {
            "name": "tasks__list_tasks", "description": "List tasks",
            "parameters": {"type": "object", "properties": {}},
        }}]
        req = LLMRequest(text="проверь задачи", context=[], available_tools=tools)
        with patch("httpx.AsyncClient", return_value=FakeClient()):
            resp = await router._call_local(req)

        assert "tools" in captured["json"]
        assert resp.tool_calls is not None
        assert resp.tool_calls[0].name == "tasks__list_tasks"

    async def test_route_returns_response(self, router: LLMRouter) -> None:
        req = LLMRequest(text="hello", context=[], available_tools=[])
        with patch.object(router, "_call_local", new_callable=AsyncMock) as mock_local:
            mock_local.return_value = LLMResponse(
                text="Hi!", tool_calls=None, provider_used="local", latency_ms=10
            )
            resp = await router.route(req)
            assert resp.text == "Hi!"
            assert resp.provider_used == "local"

    def test_openai_provider_config(self) -> None:
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o")
        router = LLMRouter(config)
        assert router.config.cloud_provider == "openai"
        assert router.config.cloud_model == "gpt-4o"

    async def test_route_with_openai_mock(self) -> None:
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o")
        router = LLMRouter(config)
        req = LLMRequest(text="hello", context=[], available_tools=[{"type": "function", "function": {"name": "test", "description": "test"}}])
        with patch.object(router, "_call_openai", new_callable=AsyncMock) as mock:
            mock.return_value = LLMResponse(
                text="Hello from GPT!", tool_calls=None, provider_used="openai", latency_ms=100
            )
            resp = await router.route(req)
            assert resp.text == "Hello from GPT!"
            assert resp.provider_used == "openai"
            mock.assert_called_once()

    def test_openai_token_param_selection(self) -> None:
        """GPT-5 / o-series require max_completion_tokens; older models keep max_tokens."""
        from kernel.llm_router import _openai_max_token_param

        assert _openai_max_token_param("gpt-5.4-mini") == "max_completion_tokens"
        assert _openai_max_token_param("o1-preview") == "max_completion_tokens"
        assert _openai_max_token_param("gpt-4o") == "max_tokens"

    async def test_call_openai_uses_max_completion_tokens_for_gpt5(self) -> None:
        """Regression: gpt-5.x rejects max_tokens with HTTP 400; must send max_completion_tokens."""
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-5.4-mini")
        router = LLMRouter(config)
        req = LLMRequest(text="hi", context=[], available_tools=[], system_prompt="sys")

        message = MagicMock()
        message.content = "ok"
        message.tool_calls = None
        resp_obj = MagicMock()
        resp_obj.choices = [MagicMock(message=message)]

        mock_create = AsyncMock(return_value=resp_obj)
        mock_client = MagicMock()
        mock_client.chat.completions.create = mock_create

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            await router._call_openai(req)

        kwargs = mock_create.call_args.kwargs
        assert "max_completion_tokens" in kwargs
        assert "max_tokens" not in kwargs

    async def test_route_stream_falls_back_to_full_text_with_tools(self) -> None:
        """Tool requests aren't plain-text-streamable → one delta = full route()."""
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o")
        router = LLMRouter(config)
        tools = [{"type": "function", "function": {"name": "t", "description": "t"}}]
        req = LLMRequest(text="hi", context=[], available_tools=tools)
        with patch.object(router, "route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = LLMResponse(
                text="full answer", tool_calls=None, provider_used="openai", latency_ms=0
            )
            out = [d async for d in router.route_stream(req)]
        assert out == ["full answer"]

    async def test_route_stream_yields_openai_deltas(self) -> None:
        """No tools + cloud OpenAI → stream deltas verbatim."""
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o", auto_route=True)
        router = LLMRouter(config)
        req = LLMRequest(text="hi", context=[], available_tools=[])

        async def fake_stream(_req):
            for delta in ["При", "вет", ", сэр."]:
                yield delta

        with patch.object(router, "_stream_openai", fake_stream):
            out = [d async for d in router.route_stream(req)]
        assert out == ["При", "вет", ", сэр."]

    async def test_route_streaming_streams_and_returns_full(self) -> None:
        """route_streaming feeds deltas to the callback and returns the full text."""
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o", auto_route=True)
        router = LLMRouter(config)
        req = LLMRequest(text="hi", context=[], available_tools=[])

        async def fake_stream(_req):
            for delta in ["При", "вет."]:
                yield delta

        deltas: list[str] = []

        async def on_delta(d: str) -> None:
            deltas.append(d)

        with patch.object(router, "_stream_openai", fake_stream):
            resp = await router.route_streaming(req, on_delta)

        assert deltas == ["При", "вет."]
        assert resp.text == "Привет."
        assert resp.tool_calls is None

    async def test_route_streaming_empty_falls_back_for_tool_call(self) -> None:
        """An empty stream (the model chose a tool call) recovers via route()."""
        config = LLMConfig(cloud_provider="openai", cloud_model="gpt-4o", auto_route=True)
        router = LLMRouter(config)
        tools = [{"type": "function", "function": {"name": "t", "description": "t"}}]
        req = LLMRequest(text="hi", context=[], available_tools=tools)

        async def empty_stream(_req):
            for _ in []:
                yield _

        tool_resp = LLMResponse(
            text="",
            tool_calls=[ToolCall(name="t", arguments={})],
            provider_used="openai",
            latency_ms=0,
        )
        deltas: list[str] = []

        async def on_delta(d: str) -> None:
            deltas.append(d)

        with patch.object(router, "_stream_openai", empty_stream), patch.object(
            router, "route", new_callable=AsyncMock
        ) as mock_route:
            mock_route.return_value = tool_resp
            resp = await router.route_streaming(req, on_delta)

        assert deltas == []
        assert resp.tool_calls is not None
        mock_route.assert_awaited_once()
