"""Voice pipeline must EXECUTE tool calls, not just announce them (core-loop 1a)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from kernel.event_bus import EventBus
from kernel.llm_router import LLMResponse, ToolCall
from kernel.models import LLMConfig, VoiceConfig
from kernel.voice.pipeline import PipelineState
from kernel.voice.remote_pipeline import RemoteVoicePipeline


async def test_remote_pipeline_executes_tool_call_and_speaks_result() -> None:
    app_state = MagicMock()
    app_state.long_term_memory = None
    manifest = MagicMock()
    manifest.protocol = "native"
    app_state.plugin_registry.get.return_value = manifest
    app_state.agent_runtime.load_agent = AsyncMock()
    app_state.agent_runtime.dispatch = AsyncMock(return_value={"tasks": []})

    pipe = RemoteVoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=[],
        app_state=app_state,
    )

    stt_result = SimpleNamespace(
        text="проверь задачи", is_empty=False, confidence=0.9, language="ru", duration_ms=500
    )
    fake_stt = MagicMock()
    fake_stt.transcribe.return_value = stt_result

    # The model chooses a tool (streamed text empty); the second pass phrases it.
    async def fake_route_streaming(request, on_delta):  # noqa: ANN001
        return LLMResponse(
            text="",
            tool_calls=[ToolCall(name="tasks__list_tasks", arguments={})],
            provider_used="openai",
            latency_ms=5,
        )

    pipe._llm.route_streaming = fake_route_streaming
    pipe._llm.route = AsyncMock(
        return_value=LLMResponse(
            text="Задач нет, сэр.", tool_calls=None, provider_used="openai", latency_ms=5
        )
    )

    spoken: list[str] = []

    async def fake_emit(text: str) -> None:
        spoken.append(text)

    pipe._emit_tts_for = fake_emit  # type: ignore[method-assign]
    pipe._audio_buffer = [np.zeros(1600, dtype=np.int16).tobytes()]

    with patch("kernel.voice.transcribe_helper.get_or_create_stt", return_value=fake_stt):
        await pipe._process_utterance()

    # The tool actually ran (not just announced)...
    app_state.agent_runtime.dispatch.assert_awaited_once_with("tasks", "list_tasks", {})
    # ...and the real result was spoken back to the user.
    assert "Задач нет, сэр." in spoken
    assert pipe._state == PipelineState.IDLE


def _make_pipe(app_state: object, tools: list | None = None) -> RemoteVoicePipeline:
    return RemoteVoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=tools or [],
        app_state=app_state,
    )


def test_live_tools_reads_registry_each_turn() -> None:
    """A skill created mid-session must be callable by voice, so the palette is
    read live from the registry rather than a startup snapshot (core-loop 1c)."""
    app_state = MagicMock()
    sentinel = [{"type": "function", "function": {"name": "new-skill__do", "description": "d"}}]
    app_state.plugin_registry.get_all_tools.return_value = sentinel
    pipe = _make_pipe(app_state, tools=[])  # startup snapshot was empty
    assert pipe._live_tools() == sentinel


def test_live_tools_falls_back_to_snapshot_without_state() -> None:
    snapshot = [{"type": "function", "function": {"name": "x__y", "description": "d"}}]
    pipe = _make_pipe(None, tools=snapshot)
    assert pipe._live_tools() == snapshot
