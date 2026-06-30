"""Tests for builder trigger detection in voice pipeline."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from kernel.voice.pipeline import _detect_builder_trigger


@pytest.mark.parametrize("text,expected", [
    ("Создай агента чтобы напоминал пить воду", True),
    ("Сделай агента для отслеживания курса биткоина", True),
    ("Сделай скилл напоминалку", True),
    ("Создай скилл для дневника настроения", True),
    ("Какая погода?", False),
    ("Открой калькулятор", False),
    ("", False),
])
def test_detect_builder_trigger(text: str, expected: bool) -> None:
    assert _detect_builder_trigger(text) == expected


@pytest.mark.asyncio
async def test_multi_turn_flow_reaches_deploy(monkeypatch):
    """Turn 1: trigger → start. Turn 2: answer → preview. Turn 3: 'да' → deploy."""
    from kernel.voice.pipeline import VoicePipeline
    from kernel.models import VoiceConfig, LLMConfig
    from kernel.event_bus import EventBus
    from kernel.voice.stt import STTResult

    flow = MagicMock()
    flow.start = MagicMock(return_value={
        "session_id": "sid1",
        "question": "Как часто напоминать?",
        "total_steps": 1,
    })
    flow.answer = MagicMock(return_value={
        "done": True,
        "preview": {"name": "water-reminder", "description": "Напоминалка"},
    })
    flow.deploy = AsyncMock(return_value={"status": "deployed", "name": "water-reminder"})
    flow.cancel = MagicMock()

    app_state = MagicMock()
    app_state.builder_flow = flow

    pipe = VoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=[],
        app_state=app_state,
    )
    # Stub TTS playback
    pipe._speak = AsyncMock()

    # Turn 1 — trigger
    await pipe._handle_transcription(STTResult(
        text="Создай агента для напоминаний", language="ru", confidence=1.0, duration_ms=100,
    ))
    assert pipe._active_builder_session == "sid1"

    # Turn 2 — answer (result.done=True → preview)
    await pipe._handle_transcription(STTResult(
        text="каждые 2 часа", language="ru", confidence=1.0, duration_ms=100,
    ))
    assert pipe._awaiting_deploy_confirm is True

    # Turn 3 — "да" → deploy
    await pipe._handle_transcription(STTResult(
        text="да", language="ru", confidence=1.0, duration_ms=100,
    ))
    flow.deploy.assert_awaited_once_with("sid1")
    assert pipe._active_builder_session is None
    assert pipe._awaiting_deploy_confirm is False


def _confirm_pipe() -> tuple["VoicePipeline", MagicMock]:  # type: ignore[name-defined]
    """A pipeline parked at the deploy-confirmation step."""
    from kernel.voice.pipeline import VoicePipeline
    from kernel.models import VoiceConfig, LLMConfig
    from kernel.event_bus import EventBus

    flow = MagicMock()
    flow.deploy = AsyncMock(return_value={"status": "deployed", "name": "x"})
    flow.cancel = MagicMock()
    app_state = MagicMock()
    app_state.builder_flow = flow

    pipe = VoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=[],
        app_state=app_state,
    )
    pipe._speak = AsyncMock()
    pipe._awaiting_deploy_confirm = True
    pipe._active_builder_session = "sid1"
    return pipe, flow


@pytest.mark.asyncio
async def test_deploy_confirm_ignores_substring_da() -> None:
    """«даже не думай» must NOT trigger deploy via a 'да' substring match."""
    from kernel.voice.stt import STTResult

    pipe, flow = _confirm_pipe()
    await pipe._handle_transcription(STTResult(
        text="даже не думай", language="ru", confidence=1.0, duration_ms=100,
    ))
    flow.deploy.assert_not_awaited()  # 'даже' must not match whole-word 'да'
    # No whole-word positive AND no negative → re-ask, stay parked.
    flow.cancel.assert_not_called()
    assert pipe._awaiting_deploy_confirm is True


@pytest.mark.asyncio
async def test_deploy_confirm_word_da_deploys() -> None:
    """A genuine «да, запускай» still deploys."""
    from kernel.voice.stt import STTResult

    pipe, flow = _confirm_pipe()
    await pipe._handle_transcription(STTResult(
        text="да, запускай", language="ru", confidence=1.0, duration_ms=100,
    ))
    flow.deploy.assert_awaited_once_with("sid1")
