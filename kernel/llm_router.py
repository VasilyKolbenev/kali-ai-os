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
    system_prompt: str | None = None


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
        self._local_available = True
        self._local_fails = 0
        self._local_last_fail = 0.0

    def select_provider(self, request: LLMRequest) -> str:
        if request.force_provider:
            return request.force_provider

        if not self.config.auto_route:
            return "cloud"

        if not self._local_available and (time.time() - self._local_last_fail > 300):
            self._local_available = True
            self._local_fails = 0

        # Prioritize cloud (much faster, always works)
        if self._cloud_available:
            return "cloud"

        return "local" if self._local_available else "cloud"

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
                self._local_fails += 1
                if self._local_fails >= 2:
                    self._local_available = False
                    self._local_last_fail = time.time()
                    
                response = await self._call_cloud(request) if self._cloud_available else LLMResponse(
                    text="I'm sorry, I couldn't process that request.",
                    tool_calls=None,
                    provider_used="error",
                    latency_ms=0,
                )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        response.latency_ms = elapsed_ms
        return response

    async def _call_cloud(self, request: LLMRequest) -> LLMResponse:
        provider = self.config.cloud_provider
        if provider == "openai":
            return await self._call_openai(request)
        elif provider == "google":
            return await self._call_google(request)
        elif provider == "deepseek":
            return await self._call_openai_compat(
                request, base_url="https://api.deepseek.com/v1", api_key_env="DEEPSEEK_API_KEY", provider_name="deepseek"
            )
        elif provider == "groq":
            return await self._call_openai_compat(
                request, base_url="https://api.groq.com/openai/v1", api_key_env="GROQ_API_KEY", provider_name="groq"
            )
        elif provider == "mistral":
            return await self._call_openai_compat(
                request, base_url="https://api.mistral.ai/v1", api_key_env="MISTRAL_API_KEY", provider_name="mistral"
            )
        return await self._call_anthropic(request)

    async def _call_anthropic(self, request: LLMRequest) -> LLMResponse:
        """Call Claude API via anthropic SDK."""
        import anthropic
        from kernel.jarvis_persona import get_prompt

        client = anthropic.AsyncAnthropic()
        messages = [{"role": "user", "content": request.text}]

        for ctx in request.context:
            messages.insert(-1, ctx)

        system_prompt = request.system_prompt or get_prompt()

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": messages,
            "metadata": {"user_id": "local_desktop"},
        }

        if request.available_tools:
            kwargs["tools"] = request.available_tools

        try:
            response = await client.messages.create(**kwargs)
        except Exception as e:
            logger.error("Anthropic API error: %s", e)
            raise

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
        from kernel.jarvis_persona import get_prompt

        client = openai.AsyncOpenAI()
        system_prompt = request.system_prompt or get_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        for ctx in request.context:
            messages.append(ctx)
        messages.append({"role": "user", "content": request.text})

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "messages": messages,
            "max_tokens": 4096,
            "user": "local_desktop",
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

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error("OpenAI API error: %s", e)
            raise

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
                timeout=3.0,
            )
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            tool_calls=None,
            provider_used="local",
            latency_ms=0,
        )

    async def _call_google(self, request: LLMRequest) -> LLMResponse:
        """Call Google Gemini API via google-genai SDK."""
        from google import genai
        from kernel.jarvis_persona import get_prompt

        client = genai.Client()
        system_prompt = request.system_prompt or get_prompt()

        contents = []
        for ctx in request.context:
            contents.append(genai.types.Content(
                role=ctx.get("role", "user"),
                parts=[genai.types.Part(text=ctx.get("content", ""))],
            ))
        contents.append(genai.types.Content(
            role="user",
            parts=[genai.types.Part(text=request.text)],
        ))

        config = genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            safety_settings=[
                genai.types.SafetySetting(
                    category=genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=genai.types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
                )
            ],
        )

        try:
            response = await client.aio.models.generate_content(
                model=self.config.cloud_model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            logger.error("Google API error: %s", e)
            raise

        text = response.text or ""
        return LLMResponse(
            text=text,
            tool_calls=None,
            provider_used="google",
            latency_ms=0,
        )

    async def _call_openai_compat(
        self,
        request: LLMRequest,
        *,
        base_url: str,
        api_key_env: str,
        provider_name: str,
    ) -> LLMResponse:
        """Call any OpenAI-compatible API (DeepSeek, Groq, Mistral, etc.)."""
        import os

        import openai
        from kernel.jarvis_persona import get_prompt

        api_key = os.environ.get(api_key_env, "")
        client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)

        system_prompt = request.system_prompt or get_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        for ctx in request.context:
            messages.append(ctx)
        messages.append({"role": "user", "content": request.text})

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "messages": messages,
            "max_tokens": 4096,
            "user": "local_desktop",
        }

        if request.available_tools:
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

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error("OpenAI-compatible API error: %s", e)
            raise

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
            provider_used=provider_name,
            latency_ms=0,
        )

