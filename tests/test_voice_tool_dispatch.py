"""Voice pipelines must EXECUTE tool calls through the REAL dispatch path.

The spine sprint made both voice pipelines, after ``route()``, dispatch
``response.tool_calls`` via :func:`kernel.tool_dispatch.execute_tool_call` and
speak the REAL dispatched result instead of merely announcing the call and
going idle (the old behaviour: a spoken command that needed an agent did
nothing).

Existing coverage stops short of proving the wiring end to end:
- ``tests/kernel/voice/test_remote_pipeline.py`` drives the pipeline but with a
  *MagicMock* ``plugin_registry``/``agent_runtime`` (the dispatch is mocked).
- ``tests/e2e/test_core_loop_build_deploy.py`` uses a REAL registry + executor
  but calls ``execute_tool_call`` directly, NOT through the pipeline.

These tests close that gap: they drive each pipeline's transcription→route→
dispatch path with a **real** :class:`~kernel.plugin_registry.PluginRegistry`,
a **real** :class:`~kernel.skill_executor.SkillExecutor`, and the **real**
``tool_dispatch`` module. Only the boundaries are stubbed — STT input, the LLM
router, and the TTS sink. The thing under test (does the spoken result reflect
a tool the executor actually ran?) is exercised with live components.

ML-free: template skills run in-process; no torch/F5/whisper.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import yaml

from kernel.event_bus import EventBus
from kernel.llm_router import LLMResponse, ToolCall
from kernel.models import LLMConfig, VoiceConfig
from kernel.plugin_registry import PluginRegistry
from kernel.skill_executor import SkillExecutor
from kernel.voice.pipeline import PipelineState, VoicePipeline
from kernel.voice.remote_pipeline import RemoteVoicePipeline

# Phrase the second-pass LLM emits after seeing the real tool result. Distinct
# from a bare "Готово" so the assertion proves the spoken text came from the
# dispatched result path, not a hardcoded ack.
SPOKEN_SUMMARY = "Записал 200 мл воды, сэр."


@pytest.fixture
def water_skill_state(tmp_path: Path) -> SimpleNamespace:
    """A real, callable water-tracker skill backed by real registry + executor.

    Mirrors the on-disk shape the builder deploys (manifest.yaml advertises the
    tools; skill.yaml binds the tracker template so the executor can run it).
    Returns an ``app_state`` exposing the two collaborators the dispatch path
    reads (``plugin_registry``, ``skill_executor``); ``agent_runtime`` is unused
    for a skill-protocol dispatch and left None.
    """
    agents_dir = tmp_path / "agents"
    skill_dir = agents_dir / "water-tracker"
    skill_dir.mkdir(parents=True)
    manifest = {
        "name": "water-tracker",
        "version": "1.0.0",
        "description": "Track water intake",
        "protocol": "skill",
        "tools": [
            {
                "name": "log",
                "description": "Log water intake",
                "parameters": {"amount": {"type": "number"}},
            }
        ],
        "permissions": ["storage"],
    }
    (skill_dir / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    skill_config = {
        "template": "tracker",
        "display_name": "Трекер воды",
        "config": {"unit": "мл", "daily_goal": 2000},
    }
    (skill_dir / "skill.yaml").write_text(yaml.dump(skill_config), encoding="utf-8")

    registry = PluginRegistry(agents_dir=agents_dir)
    registry.discover()  # real load → water-tracker__log enters get_all_tools()

    executor = SkillExecutor(data_dir=tmp_path / "data")
    executor.load_skill(skill_dir)  # real template; execute() really runs

    return SimpleNamespace(
        plugin_registry=registry,
        skill_executor=executor,
        agent_runtime=None,
        long_term_memory=None,
        builder_flow=None,
    )


def _stub_router(pipe: Any) -> None:
    """Stub ONLY the LLM boundary on a pipeline's real router.

    Branches on the request, not call order, so it behaves identically for both
    pipelines (desktop's first LLM call is ``route``; remote's is
    ``route_streaming`` followed by a ``route`` phrasing pass):

    - tool-choice pass (carries the live ``available_tools`` palette) → the
      model picks the water-tracker tool, no plain-text answer;
    - phrasing pass (``execute_tool_call`` calls ``route`` with
      ``available_tools=[]``) → returns SPOKEN_SUMMARY for the raw result.

    The router instance and tool_dispatch remain real.
    """
    tool_resp = LLMResponse(
        text="",
        tool_calls=[ToolCall(name="water-tracker__log", arguments={"amount": 200})],
        provider_used="stub",
        latency_ms=0,
    )
    summary_resp = LLMResponse(
        text=SPOKEN_SUMMARY, tool_calls=None, provider_used="stub", latency_ms=0
    )

    async def fake_route(request: Any) -> LLMResponse:
        return tool_resp if request.available_tools else summary_resp

    pipe._llm.route = fake_route  # type: ignore[method-assign]

    # Remote routes the tool-choice pass via route_streaming (empty deltas =
    # "model chose a tool"); the dispatch then runs and route() phrases it.
    async def fake_route_streaming(_request: Any, _on_delta: Any) -> LLMResponse:
        return tool_resp

    pipe._llm.route_streaming = fake_route_streaming  # type: ignore[method-assign]


async def test_desktop_pipeline_executes_tool_and_speaks_real_result(
    water_skill_state: SimpleNamespace,
) -> None:
    """pipeline.py: a spoken command runs the real skill and speaks its result."""
    pipe = VoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=[],
        app_state=water_skill_state,
    )
    _stub_router(pipe)

    spoken: list[str] = []

    async def capture_tts(text: str) -> None:
        spoken.append(text)

    # TTS sink stubbed (no audio hardware); state machine stays real.
    pipe._play_tts_with_guard = capture_tts  # type: ignore[method-assign]

    stt_result = SimpleNamespace(
        text="запиши 200 мл воды",
        is_empty=False,
        language="ru",
        confidence=0.95,
        duration_ms=400,
    )
    await pipe._handle_transcription(stt_result)

    # The REAL executor ran the log action: today's total reflects amount=200.
    summary = await water_skill_state.skill_executor.execute(
        "water-tracker", "summary", {}
    )
    assert summary["total"] == 200, f"tool did not actually run: {summary!r}"

    # The spoken text is the dispatched result phrasing, not a bare ack.
    assert spoken == [SPOKEN_SUMMARY]
    assert pipe.state == PipelineState.IDLE


async def test_remote_pipeline_executes_tool_and_speaks_real_result(
    water_skill_state: SimpleNamespace,
) -> None:
    """remote_pipeline.py: same proof through the WebSocket pipeline's path."""
    pipe = RemoteVoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=[],
        app_state=water_skill_state,
    )
    _stub_router(pipe)

    spoken: list[str] = []

    async def capture_emit(text: str) -> None:
        spoken.append(text)

    pipe._emit_tts_for = capture_emit  # type: ignore[method-assign]

    stt_result = SimpleNamespace(
        text="запиши 200 мл воды",
        is_empty=False,
        language="ru",
        confidence=0.95,
        duration_ms=400,
    )
    fake_stt = SimpleNamespace(transcribe=lambda _audio: stt_result)
    # One non-empty PCM chunk so _process_utterance proceeds to STT.
    pipe._audio_buffer = [np.zeros(1600, dtype=np.int16).tobytes()]

    with patch(
        "kernel.voice.transcribe_helper.get_or_create_stt", return_value=fake_stt
    ):
        await pipe._process_utterance()

    summary = await water_skill_state.skill_executor.execute(
        "water-tracker", "summary", {}
    )
    assert summary["total"] == 200, f"tool did not actually run: {summary!r}"

    # The dispatched result was spoken (emitted at least once, distinct from ack).
    assert SPOKEN_SUMMARY in spoken
    assert pipe._state == PipelineState.IDLE
