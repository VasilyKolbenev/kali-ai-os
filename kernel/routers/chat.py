"""Chat + profile («анкета») endpoints — extracted from kernel/main.py (T1).

Bodies are byte-identical to the pre-split closures except the sanctioned
signature changes (plan 2026-07-13): ``_speak_response`` takes ``app``
explicitly instead of closing over it.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from kernel.routers._shared import _play_audio

logger = logging.getLogger(__name__)

router = APIRouter()


async def _speak_response(app: Any, text: str) -> None:
    """Speak text through system speakers (fire-and-forget).

    Uses pre-recorded JARVIS clips for common phrases (greetings, ok, thanks).
    Falls back to F5-TTS / ElevenLabs for custom responses.
    Anti-echo: mutes voice pipeline microphone during playback.
    """
    import asyncio
    if not text or len(text) < 3:
        return

    # Anti-echo: stop voice pipeline mic before speaking
    vp = getattr(app.state, "voice_pipeline", None)
    was_recording = bool(vp and vp._recorder.is_recording)
    if was_recording:
        await vp._recorder.stop()

    try:
        # Try pre-recorded JARVIS clip first
        from kernel.voice.jarvis_sounds import play_reaction, should_use_clip
        clip = should_use_clip(text)
        if clip:
            await asyncio.to_thread(play_reaction, clip)
            return

        # Generate TTS for custom responses — sentence by sentence so the
        # first sentence starts playing while the rest synthesizes (P1).
        from kernel.voice.tts_router import (
            generate_audio_by_sentence,
            is_loaded,
            load_models,
        )
        if not is_loaded():
            await asyncio.to_thread(load_models)
        async for audio, sr in generate_audio_by_sentence(text):
            await asyncio.to_thread(_play_audio, audio, sr)
    except Exception as e:
        logger.warning("Auto-speak failed: %s", e)
    finally:
        # Anti-echo: 500ms buffer lets audio fully drain before mic resumes.
        # Only resume the mic if it was recording before we spoke — otherwise
        # we would turn voice on when it was off and orphan the stream.
        await asyncio.sleep(0.5)
        if was_recording:
            await vp._recorder.start()
            vp._wake_word.reset()
            vp._vad.reset()


@router.post("/chat")
async def chat(request: Request) -> dict[str, Any]:
    """Process a chat message through LLM or agents. Auto-speaks response."""
    result = await _chat_logic(request)
    # Auto-speak the response through system speakers. Retain the task in a
    # set so the GC cannot cancel it mid-speech; discard it when it finishes.
    import asyncio as _aio
    speak_task = _aio.create_task(
        _speak_response(request.app, result.get("response", ""))
    )
    request.app.state._speak_tasks.add(speak_task)
    speak_task.add_done_callback(request.app.state._speak_tasks.discard)
    return result


async def _chat_logic(request: Request) -> dict[str, Any]:
    """Internal chat logic — returns response dict using LLMRouter."""
    from kernel.llm_router import LLMRequest, LLMRouter
    from kernel.tool_dispatch import execute_tool_calls

    body = await request.json()
    text = body.get("text", "")
    if not text:
        return {"response": "Empty message", "source": "system"}

    s = request.app.state

    # Personal memory: prime the system prompt with known user facts so
    # the assistant "remembers" the user across sessions. Mirrors the
    # voice path (remote_pipeline) so chat, voice, and the Rust cutover
    # share one memory. Guarded — degrades to no-facts if unavailable.
    lt_memory = getattr(s, "long_term_memory", None)
    system_prompt = None
    if lt_memory:
        try:
            facts_context = await lt_memory.get_user_context_string()
        except Exception:
            facts_context = ""
        if facts_context:
            from kernel.jarvis_persona import get_prompt
            system_prompt = get_prompt() + "\n\n" + facts_context

    # 1. Fetch available tools from registry
    available_tools = s.plugin_registry.get_all_tools()

    # 2. Setup LLM router
    router = LLMRouter(s.config_manager.config.llm)

    # 3. First request
    req = LLMRequest(
        text=text,
        context=s.memory.get_context(),
        available_tools=available_tools,
        system_prompt=system_prompt,
    )
    response = await router.route(req)

    # No AI key / total LLM outage: the router returns provider_used="error"
    # with an English fallback. A skip-key RU non-tech user must not see that
    # dead-end — return an honest Russian prompt routing them to settings.
    if response.provider_used == "error":
        return {
            "response": "Я пока без ключа от ИИ. Открой Настройки → Модель "
            "и вставь ключ — и я сразу отвечу.",
            "source": "no-key",
        }

    # Personal memory: extract any new permanent facts from this turn
    # (fire-and-forget; never blocks the reply).
    if lt_memory:
        try:
            await lt_memory.maybe_extract_and_save_facts(text)
        except Exception as e:
            logger.warning("Background memory extraction failed: %s", e)

    # 4. Handle tool calls — shared execution path with the voice pipelines
    # (kernel/tool_dispatch.py) so chat and voice can never diverge again.
    if response.tool_calls:
        try:
            dispatched = await execute_tool_calls(
                s, router, response.tool_calls, req.context, text
            )
        except Exception as e:
            names = ", ".join(c.name for c in response.tool_calls)
            logger.exception("Tool execution failed for %s", names)
            return {"response": f"Error executing {names}: {e}", "source": "system"}
        if dispatched is not None:
            final_text, result, source = dispatched
            s.memory.add_turn("user", text)
            s.memory.add_turn("assistant", final_text)
            return {"response": final_text, "source": source, "data": result}

    # 5. Normal text response
    s.memory.add_turn("user", text)
    s.memory.add_turn("assistant", response.text)

    return {
        "response": response.text,
        "source": f"llm-{response.provider_used}",
    }


# Onboarding questionnaire («анкета»): profile fields live in user_facts
# under fixed profile.* topics with upsert semantics (see
# docs/superpowers/specs/2026-07-11-profile-anketa.md).
PROFILE_FIELDS = ("name", "gender", "occupation", "city", "age_range")
PROFILE_GENDERS = {"male": "мужской", "female": "женский"}
PROFILE_AGE_RANGES = {"18-25", "26-35", "36-45", "46-55", "55+"}
MAX_PROFILE_FIELD_CHARS = 200


@router.get("/profile")
async def get_profile(request: Request) -> dict[str, Any]:
    """Current questionnaire values (None for unset fields)."""
    facts = await request.app.state.database.get_user_facts()
    by_topic = {f["topic"]: f["fact"] for f in facts}
    out: dict[str, Any] = {}
    for field in PROFILE_FIELDS:
        value = by_topic.get(f"profile.{field}")
        if field == "gender" and value is not None:
            # Stored as the Russian fact word; API speaks enum values.
            ru_to_enum = {v: k for k, v in PROFILE_GENDERS.items()}
            value = ru_to_enum.get(value)
        out[field] = value
    return out


@router.post("/profile")
async def post_profile(request: Request) -> Any:
    """Upsert questionnaire fields. Missing = skip, "" = clear, value = set."""
    from fastapi.responses import JSONResponse

    body = await request.json()
    db = request.app.state.database
    updates: list[tuple[str, str | None]] = []
    for field in PROFILE_FIELDS:
        if field not in body:
            continue
        raw = body[field]
        if not isinstance(raw, str):
            return JSONResponse({"error": f"{field} must be a string"}, status_code=400)
        value = raw.strip()
        if value == "":
            updates.append((field, None))
            continue
        if len(value) > MAX_PROFILE_FIELD_CHARS:
            return JSONResponse({"error": f"{field} too long"}, status_code=400)
        if field == "gender":
            if value not in PROFILE_GENDERS:
                return JSONResponse({"error": "gender must be male|female"}, status_code=400)
            value = PROFILE_GENDERS[value]
        if field == "age_range" and value not in PROFILE_AGE_RANGES:
            return JSONResponse({"error": "invalid age_range"}, status_code=400)
        updates.append((field, value))

    for field, value in updates:
        topic = f"profile.{field}"
        if value is None:
            await db.delete_user_facts_by_topic(topic)
        else:
            await db.upsert_user_fact(topic, value)
    return {"status": "ok", "saved": [f for f, v in updates if v is not None]}
