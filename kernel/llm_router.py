"""LLM Router — routes requests to cloud or local LLM based on complexity."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from kernel.models import LLMConfig

logger = logging.getLogger(__name__)


def _openai_max_token_param(model: str) -> str:
    """Return the token-limit kwarg name for an OpenAI model.

    GPT-5 and o-series reasoning models reject ``max_tokens`` and require
    ``max_completion_tokens``; older chat models still accept ``max_tokens``.

    Args:
        model: The OpenAI model identifier (e.g. ``"gpt-5.4-mini"``).

    Returns:
        ``"max_completion_tokens"`` for GPT-5/o-series, else ``"max_tokens"``.
    """
    return (
        "max_completion_tokens"
        if model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
        else "max_tokens"
    )


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
        self._cloud_last_fail = 0.0
        self._local_available = True
        self._local_fails = 0
        self._local_last_fail = 0.0

    def select_provider(self, request: LLMRequest) -> str:
        if request.force_provider:
            return request.force_provider

        # auto_route disabled = the user has explicitly opted out of
        # cloud-first routing to keep generation local (privacy). The
        # mobile/desktop provider dropdown encodes a "use local" pick as
        # auto_route=false; honour it instead of silently using cloud.
        if not self.config.auto_route:
            return "local"

        if not self._local_available and (time.time() - self._local_last_fail > 300):
            self._local_available = True
            self._local_fails = 0

        # Re-enable cloud after a cooldown so a single transient cloud failure
        # doesn't strand the whole session on local — which strips tools, so
        # every agent action would silently degrade to a chat reply.
        if not self._cloud_available and (time.time() - self._cloud_last_fail > 300):
            self._cloud_available = True

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
                self._cloud_last_fail = time.time()
                response = await self._call_local(request)
            else:
                self._local_fails += 1
                if self._local_fails >= 2:
                    self._local_available = False
                    self._local_last_fail = time.time()

                # auto_route=false is an explicit local-only (privacy) choice:
                # never silently send the user's content to cloud as a fallback.
                if not self.config.auto_route:
                    response = LLMResponse(
                        text="Local LLM unavailable and cloud fallback is "
                        "disabled (local-only mode). Please start the local "
                        "model or enable auto-routing.",
                        tool_calls=None,
                        provider_used="error",
                        latency_ms=0,
                    )
                elif self._cloud_available:
                    response = await self._call_cloud(request)
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
            _openai_max_token_param(self.config.cloud_model): 4096,
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

    async def route_stream(self, request: LLMRequest):
        """Yield the response as text deltas so callers can start TTS before the
        full reply is ready (P1b — cuts the LLM-wait on top of P1a's TTS-wait).

        Falls back to a single delta (the full ``route()`` text) for cases that
        aren't plain-text-streamable: tool requests, or any provider/route other
        than cloud OpenAI. The caller still accumulates the full text for
        conversation context + long-term memory.
        """
        streamable = (
            not request.available_tools
            and self.select_provider(request) == "cloud"
            and self.config.cloud_provider == "openai"
        )
        if not streamable:
            resp = await self.route(request)
            if resp.text:
                yield resp.text
            return
        try:
            async for delta in self._stream_openai(request):
                if delta:
                    yield delta
        except Exception:
            logger.exception("LLM stream failed — falling back to non-streaming")
            resp = await self.route(request)
            if resp.text:
                yield resp.text

    async def _stream_openai(self, request: LLMRequest):
        """Stream text deltas from the OpenAI chat completions API."""
        import openai
        from kernel.jarvis_persona import get_prompt

        client = openai.AsyncOpenAI()
        system_prompt = request.system_prompt or get_prompt()
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for ctx in request.context:
            messages.append(ctx)
        messages.append({"role": "user", "content": request.text})

        kwargs: dict[str, Any] = {
            "model": self.config.cloud_model,
            "messages": messages,
            _openai_max_token_param(self.config.cloud_model): 4096,
            "user": "local_desktop",
            "stream": True,
        }
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and getattr(delta, "content", None):
                    yield delta.content

    async def route_streaming(self, request: LLMRequest, on_delta) -> LLMResponse:
        """Stream text deltas to ``on_delta`` as they arrive AND return the full
        LLMResponse (accumulated text + any tool_calls) for context, memory, and
        tool handling — the method a voice pipeline uses to start TTS on
        sentence 1 before the full reply is ready (P1b).

        Streams from cloud OpenAI; other providers emit the full text as a single
        delta. An empty stream means the model issued a tool call, which is
        recovered via a non-streaming ``route()``.
        """
        streamable = (
            self.select_provider(request) == "cloud"
            and self.config.cloud_provider == "openai"
        )
        if not streamable:
            resp = await self.route(request)
            if resp.text:
                await on_delta(resp.text)
            return resp

        parts: list[str] = []
        try:
            async for delta in self._stream_openai(request):
                if delta:
                    parts.append(delta)
                    await on_delta(delta)
        except Exception:
            logger.exception("LLM streaming failed — falling back to non-streaming")
            return await self.route(request)

        text = "".join(parts)
        if text:
            return LLMResponse(
                text=text, tool_calls=None, provider_used="openai", latency_ms=0
            )
        # Empty stream → the model chose a tool call; recover it non-streamed.
        return await self.route(request)

    async def _call_local(self, request: LLMRequest) -> LLMResponse:
        import httpx

        payload: dict[str, Any] = {
            "model": self.config.local_model,
            "messages": [{"role": "user", "content": request.text}],
            "stream": False,
        }
        # Forward tools so a local (privacy) model can still call agents. Ollama
        # accepts the same function schema and simply returns no tool_calls for a
        # model without tool support — previously these were dropped, so every
        # agent action silently degraded to a plain chat reply.
        if request.available_tools:
            payload["tools"] = request.available_tools

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json=payload,
                # Short connect timeout so a missing Ollama daemon fails
                # fast (→ cloud fallback), but a long read timeout so slow
                # local generation isn't spuriously killed and bounced to
                # cloud — which would defeat an explicit local choice.
                timeout=httpx.Timeout(60.0, connect=3.0),
            )
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                import json

                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args or {}))

        return LLMResponse(
            text=message.get("content", ""),
            tool_calls=tool_calls if tool_calls else None,
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

