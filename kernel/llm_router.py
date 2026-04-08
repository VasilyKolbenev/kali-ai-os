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
            provider_used="cloud",
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
