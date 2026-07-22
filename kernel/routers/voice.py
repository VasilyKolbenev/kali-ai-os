"""Voice / TTS / STT / model-status endpoints — extracted from kernel/main.py (T2).

Bodies are byte-identical to the pre-split closures (only ``@app.`` →
``@router.``); ``_play_audio`` comes from routers/_shared, ``logger`` is the
module logger. Def order preserves main.py registration order (sacred).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from kernel.routers._shared import _play_audio

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models/status")
async def get_models_status_api(request: Request) -> dict[str, Any]:
    from kernel.model_downloader import get_models_status
    return get_models_status()


@router.post("/models/download")
async def download_models_api(request: Request) -> dict[str, str]:
    import asyncio
    import time

    from kernel.model_downloader import download_model, get_missing_models
    from kernel.models import Event

    missing = get_missing_models()
    if not missing:
        return {"status": "ok", "message": "All models present"}

    async def _download_task() -> None:
        loop = asyncio.get_running_loop()
        event_bus = request.app.state.event_bus

        for item in missing:
            last_emit = 0.0

            def progress_cb(downloaded: int, total: int) -> None:
                nonlocal last_emit
                now = time.time()
                if now - last_emit > 0.1 or downloaded == total:
                    last_emit = now
                    asyncio.run_coroutine_threadsafe(
                        event_bus.publish(Event(
                            topic="system.models.download_progress",
                            source="kernel",
                            payload={
                                "filename": item["name"],
                                "description": item["description"],
                                "downloaded_bytes": downloaded,
                                "total_bytes": total
                            }
                        )), loop
                    )

            success = await asyncio.to_thread(download_model, item["name"], item["url"], progress_cb)
            if not success:
                # Soft failure (returned False, no raise): report it honestly
                # and do NOT fall through to a false download_complete.
                asyncio.run_coroutine_threadsafe(
                    event_bus.publish(Event(
                        topic="system.models.download_failed",
                        source="kernel",
                        payload={
                            "filename": item["name"],
                            "error": f"download_model returned False for {item['name']}",
                        },
                    )), loop
                )
                return

        asyncio.run_coroutine_threadsafe(
            event_bus.publish(Event(
                topic="system.models.download_complete",
                source="kernel",
                payload={}
            )), loop
        )

    def _on_download_done(task: asyncio.Task[None]) -> None:
        """Surface a stalled/failed download as an event so the UI can react.

        Without this a GC-cancelled or crashed task leaves the onboarding
        UI hanging on a download_complete that never arrives.
        """
        if task.cancelled():
            exc: BaseException | None = asyncio.CancelledError()
        else:
            exc = task.exception()
        if exc is None:
            return
        logger.error("Model download task exited abnormally", exc_info=exc)
        # Retain the publish task so the GC cannot cancel it before the
        # failure event reaches the bus; discard it when it finishes.
        state = request.app.state
        publish_task = asyncio.create_task(
            state.event_bus.publish(Event(
                topic="system.models.download_failed",
                source="kernel",
                payload={"error": str(exc) or type(exc).__name__},
            ))
        )
        state._download_publish_tasks.add(publish_task)
        publish_task.add_done_callback(state._download_publish_tasks.discard)

    task = asyncio.create_task(_download_task())
    request.app.state._model_download_task = task
    task.add_done_callback(_on_download_done)
    return {"status": "started", "message": "Download task started"}


@router.get("/voice/status")
async def voice_status(request: Request) -> dict[str, Any]:
    vp = request.app.state.voice_pipeline
    if vp is None:
        return {
            "available": False,
            "ready": False,
            "started": False,
            "state": "idle",
            "mode": "unavailable",
            "models_ready": False,
            "missing_models": [],
        }

    try:
        from kernel.model_downloader import get_models_status

        model_status = get_models_status()
    except Exception:
        model_status = {
            "ready": False,
            "missing_downloadable": [],
            "missing_bundled": [],
            "models_dir": "",
        }

    try:
        from kernel.voice.tts_router import is_loaded as tts_is_loaded

        tts_loaded = tts_is_loaded()
    except Exception:
        tts_loaded = False

    missing_models = [
        *model_status.get("missing_bundled", []),
        *model_status.get("missing_downloadable", []),
    ]
    ready = bool(
        vp.is_started
        and vp._vad.is_loaded
        and vp._wake_word.is_loaded
        and vp._stt.is_loaded
        and tts_loaded
        and model_status.get("ready")
    )

    return {
        "available": True,
        "ready": ready,
        "started": vp.is_started,
        "state": vp.state.value,
        "mode": vp.mode,
        "vad_loaded": vp._vad.is_loaded,
        "wake_word_loaded": vp._wake_word.is_loaded,
        "stt_loaded": vp._stt.is_loaded,
        "tts_loaded": tts_loaded,
        "models_ready": model_status.get("ready", False),
        "models_dir": model_status.get("models_dir", ""),
        "missing_models": missing_models,
    }


@router.post("/voice/start")
async def voice_start(request: Request) -> Any:
    vp = request.app.state.voice_pipeline
    if vp is None:
        return {"status": "error", "message": "Voice pipeline not available"}
    if vp.is_started:
        return {"status": "already_running"}
    # OPUS-102: load VAD/wake/STT/TTS through the coordinator (daemon threads,
    # single-flight, torch-ordered) — NOT vp.load_models() which blocks the event
    # loop and bypasses the single owner. Start the realtime loop only once every
    # required component is READY, so no early utterance is dropped.
    from fastapi.responses import JSONResponse

    from kernel.model_coordinator import ModelOutcome

    coord = getattr(request.app.state, "model_coordinator", None)
    if coord is not None:
        outcomes = {m: await coord.ensure_ready(m) for m in ("vad", "wake", "stt", "tts")}
        if not all(o is ModelOutcome.READY for o in outcomes.values()):
            request.app.state.voice_start_error = (
                f"components not ready: {{{', '.join(f'{m}:{o.value}' for m, o in outcomes.items())}}}"
            )
            return JSONResponse(
                {"status": "error", "reason": "model_unavailable",
                 "states": {m: o.value for m, o in outcomes.items()}},
                status_code=503,
            )
    await vp.start()
    request.app.state.voice_start_error = None  # success clears any prior error
    return {"status": "started"}


@router.post("/voice/stop")
async def voice_stop(request: Request) -> dict[str, str]:
    vp = request.app.state.voice_pipeline
    if vp is None:
        return {"status": "error", "message": "Voice pipeline not available"}
    await vp.stop()
    return {"status": "stopped"}


@router.post("/voice/clone")
async def voice_clone(request: Request) -> dict[str, Any]:
    """Trigger ElevenLabs voice cloning from JARVIS Sound Pack.

    Requires:
    - ELEVENLABS_API_KEY set (in Settings or .env)
    - ElevenCreator / ElevenAgents subscription (not just Pay-as-you-go)
    - Reference clips in Sound Pack directory

    Returns voice_id on success, or error details.
    """
    try:
        from kernel.voice.tts_engine_elevenlabs import ElevenLabsEngine
        engine = ElevenLabsEngine()
        auth = engine.check_auth()
        if not auth.get("ok"):
            return {"status": "error", "stage": "auth", "message": auth.get("error", "unknown")}
        # Force re-clone (ignore cached voice_id)
        engine.voice_id = None
        voice_id = engine.ensure_voice_clone()
        return {"status": "ok", "voice_id": voice_id}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _require_voice_model(request: Request, name: str) -> None:
    """Fail-closed on-demand load via the ModelCoordinator (single-flight, shared
    with prewarm). Raises :class:`ModelUnavailable` unless the model is READY, so
    the caller returns a typed 409/503 and NEVER touches Python TTS/STT after a
    DISABLED/FAILED/TIMEOUT outcome (OPUS-102 #1/#4). No-op only if the coordinator
    is absent (legacy)."""
    from kernel.model_coordinator import ModelOutcome, ModelUnavailable

    coord = getattr(request.app.state, "model_coordinator", None)
    if coord is None or not coord.has(name):
        return
    # Waiting API (bounded): shares the single-flight completion — a concurrent
    # prewarm and this request never start a 2nd loader.
    outcome = await coord.ensure_ready(name)
    if outcome is not ModelOutcome.READY:
        raise ModelUnavailable(name, outcome)


def _model_unavailable_response(exc: Any) -> Any:
    """Machine-readable 409 (engine owned by Rust) / 503 (unavailable) response."""
    from fastapi.responses import JSONResponse

    from kernel.model_coordinator import ModelOutcome

    if exc.outcome is ModelOutcome.DISABLED:
        return JSONResponse(
            {"error": "voice engine owned by Rust", "reason": "engine_owned_by_rust",
             "model": exc.name, "state": exc.outcome.value},
            status_code=409,
        )
    return JSONResponse(
        {"error": "voice model unavailable", "reason": "model_unavailable",
         "model": exc.name, "state": exc.outcome.value},
        status_code=503,
    )


@router.post("/tts")
async def text_to_speech(request: Request) -> Any:
    """Convert text to speech — F5-TTS (local GPU) or ElevenLabs (cloud)."""
    import asyncio

    from fastapi.responses import JSONResponse, Response

    body = await request.json()
    text = body.get("text", "")
    language = body.get("language")
    play = body.get("play", False)
    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)

    from kernel.model_coordinator import ModelUnavailable

    try:
        await _require_voice_model(request, "tts")
    except ModelUnavailable as e:
        return _model_unavailable_response(e)

    try:
        from kernel.voice.tts_router import audio_to_wav_bytes, generate_audio

        audio, sr = await asyncio.to_thread(generate_audio, text, language)

        # Play through system speakers if requested
        if play:
            await asyncio.to_thread(_play_audio, audio, sr)

        wav_bytes = audio_to_wav_bytes(audio, sr)
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        logger.exception("TTS failed for: '%s'", text[:80])
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/tts/speak")
async def tts_speak(request: Request) -> dict[str, Any]:
    """Synthesize and play through system speakers directly."""
    import asyncio
    import json as _json

    # Handle encoding issues from Tauri WebView2
    raw = await request.body()
    try:
        body = _json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        body = _json.loads(raw.decode("utf-8", errors="replace"))
    text = body.get("text", "")
    language = body.get("language")
    if not text:
        return {"error": "No text provided"}

    from kernel.model_coordinator import ModelUnavailable

    try:
        await _require_voice_model(request, "tts")
    except ModelUnavailable as e:
        return _model_unavailable_response(e)

    try:
        from kernel.voice.tts_router import generate_audio

        audio, sr = await asyncio.to_thread(generate_audio, text, language)
        await asyncio.to_thread(_play_audio, audio, sr)
        return {"status": "ok", "duration": len(audio) / sr}
    except Exception as e:
        logger.exception("TTS speak failed: '%s'", text[:80])
        return {"error": str(e)}


@router.post("/synthesize")
async def synthesize_endpoint(request: Request) -> Any:
    """Alias for /tts — backward compat with TTS client and frontend."""
    return await text_to_speech(request)


@router.post("/voice/transcribe")
async def voice_transcribe(request: Request) -> Any:
    """One-shot STT for the voice-builder pilot.

    Bypasses the orchestrated wake-word pipeline — uses an
    in-process SpeechToText (lazy-instantiated on first request,
    cached on app.state.stt) and reuses the i16 LE PCM decode +
    scipy resample logic from the bridge worker.
    """
    import asyncio
    import time

    from fastapi.responses import JSONResponse

    from kernel.voice.transcribe_helper import (
        decode_and_resample,
        get_or_create_stt,
    )

    body = await request.json()
    audio_b64 = body.get("audio_b64")
    if not audio_b64:
        return JSONResponse(
            {"error": "audio_b64 required"}, status_code=400
        )
    sample_rate = int(body.get("sample_rate", 16000))
    language = body.get("language")

    try:
        audio_f32, target_sr = decode_and_resample(audio_b64, sample_rate)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    from kernel.model_coordinator import ModelUnavailable

    try:
        await _require_voice_model(request, "stt")
    except ModelUnavailable as e:
        return _model_unavailable_response(e)

    try:
        stt = await asyncio.to_thread(get_or_create_stt, request.app.state)
    except Exception as e:
        logger.exception("/voice/transcribe failed to init SpeechToText")
        return JSONResponse({"error": str(e)}, status_code=500)

    t0 = time.perf_counter()
    try:
        if language and stt._model is not None:
            segments, info = await asyncio.to_thread(
                stt._model.transcribe,
                audio_f32,
                beam_size=5,
                language=language,
                vad_filter=True,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            detected_language = info.language
        else:
            result = await asyncio.to_thread(
                stt.transcribe, audio_f32, sample_rate=target_sr
            )
            text = result.text
            detected_language = result.language
    except Exception as e:
        logger.exception("/voice/transcribe failed")
        return JSONResponse({"error": str(e)}, status_code=500)

    return {
        "text": text,
        "language": detected_language,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }


@router.get("/health/tts")
async def tts_health() -> dict[str, Any]:
    """TTS engine health check."""
    try:
        from kernel.model_downloader import get_models_status
        from kernel.voice.tts_router import get_provider, is_loaded

        loaded = is_loaded()
        engine = get_provider()
        model_status = get_models_status()
    except Exception:
        loaded = False
        engine = "unknown"
        model_status = {
            "ready": False,
            "missing_downloadable": [],
            "missing_bundled": [],
            "models_dir": "",
        }
    return {
        "status": "ok" if loaded else "not loaded",
        "engine": engine,
        "models_ready": model_status.get("ready", False),
        "models_dir": model_status.get("models_dir", ""),
        "missing_models": [
            *model_status.get("missing_bundled", []),
            *model_status.get("missing_downloadable", []),
        ],
    }


# Duplicate of GET /models/status (pre-split main.py had both defs; FastAPI
# registers both but the FIRST one above wins on matching). Kept, in the same
# relative order, to preserve observed behavior byte-for-byte.
@router.get("/models/status")
async def models_status() -> dict[str, Any]:
    """Voice model availability for desktop diagnostics."""
    from kernel.model_downloader import get_models_status

    return get_models_status()
