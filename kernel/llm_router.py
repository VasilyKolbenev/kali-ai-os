"""LLM Router — routes requests to cloud or local LLM based on complexity."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from kernel.models import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    """Request to the LLM router."""

    text: str
    context: list[dict[str, Any]]
    available_tools: list[dict[str, Any]]
    force_provider: str | None = None


@dataclass
class ToolCall:
    """A tool call from the LLM."""

    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from the LLM router."""

    text: str
    tool_calls: list[ToolCall] | None
    provider_used: str
    latency_ms: int


class LLMRouter:
    """Routes LLM requests to cloud (Claude) or local (Ollama) providers.

    Routing logic:
    - Has tools + internet -> cloud (better function calling)
    - No tools needed -> local (faster)
    - force_provider overrides auto-routing
    - No internet -> local fallback
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._cloud_available = True

    def select_provider(self, request: LLMRequest) -> str:
        if request.force_provider:
            return request.force_provider

        if not self.config.auto_route:
            return "cloud"

        if request.available_tools and self._cloud_available:
            return "cloud"

        return "local"

    async def route(self, request: LLMRequest) -> LLMResponse:
        provider = self.select_provider(request)
        start = time.perf_counter()

        try:
            if provider == "cloud":
                response = await self._call_cloud(request)
            else:
                response = await self._call_local(request)
        except Exception:
            logger.exception("LLM call failed (provider=%s), trying fallback", provider)
            if provider == "cloud":
                self._cloud_available = False
                response = await self._call_local(request)
            else:
                response = LLMResponse(
                    text="I'm sorry, I couldn't process that request.",
                    tool_calls=None,
                    provider_used="error",
                    latency_ms=0,
                )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        response.latency_ms = elapsed_ms
        return response

    async def _call_cloud(self, request: LLMRequest) -> LLMResponse:
        if self.config.cloud_provider == "openai":
            return await self._call_openai(request)
        return await self._call_anthropic(request)

    async def _call_anthropic(self, request: LLMRequest) -> LLMResponse:
        """Call Claude API via anthropic SDK."""
        import anthropic

        client = anthropic.AsyncAnthropic()
        messages = [{"role": "user", "content": request.text}]

        for ctx in request.context:
            messages.insert(-1, ctx)

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "max_tokens": 1024,
            "messages": messages,
        }

        if request.available_tools:
            kwargs["tools"] = request.available_tools

        response = await client.messages.create(**kwargs)

        text = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(name=block.name, arguments=dict(block.input)))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls if tool_calls else None,
            provider_used="anthropic",
            latency_ms=0,
        )

    async def _call_openai(self, request: LLMRequest) -> LLMResponse:
        """Call OpenAI API via openai SDK."""
        import openai

        client = openai.AsyncOpenAI()
        messages: list[dict[str, Any]] = []

        for ctx in request.context:
            messages.append(ctx)
        messages.append({"role": "user", "content": request.text})

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "messages": messages,
        }

        if request.available_tools:
            # Convert Anthropic tool format to OpenAI format
            openai_tools = []
            for tool in request.available_tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["function"]["name"],
                        "description": tool["function"].get("description", ""),
                        "parameters": tool["function"].get("parameters", {}),
                    },
                })
            kwargs["tools"] = openai_tools

        response = await client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls: list[ToolCall] = []

        if choice.message.tool_calls:
            import json

            for tc in choice.message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls if tool_calls else None,
            provider_used="openai",
            latency_ms=0,
        )

    async def _call_local(self, request: LLMRequest) -> LLMResponse:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": self.config.local_model,
                    "messages": [{"role": "user", "content": request.text}],
                    "stream": False,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            tool_calls=None,
            provider_used="local",
            latency_ms=0,
        )
