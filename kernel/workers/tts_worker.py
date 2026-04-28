"""Python TTS worker. Spawned by Rust over stdio.

Protocol: line-delimited JSON, one object per line. Reads requests from
stdin, writes responses (and unsolicited log lines) to stdout. Stderr is
inherited from the parent and used for arbitrary debug output.

Requests:
    {"id": "<uuid>", "op": "<op_name>", "args": {...}}

Responses:
    {"id": "<uuid>", "result": {...}}                          # success
    {"id": "<uuid>", "error": {"type": "...", "message": "..."}}  # failure

Unsolicited log lines (no `id`):
    {"log": {"level": "info|warn|error", "message": "..."}}

This is the Phase 3 Chunk 1 shell — only `ping` is wired. Chunk 2 adds
`tts_speak` (ruaccent + F5-TTS). See
`docs/superpowers/plans/2026-05-23-rust-migration-phase-3.md` for the
full protocol spec.
"""

import base64
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

# Force HF_HOME to a project-local cache BEFORE any HF-using import
# (faster-whisper, huggingface_hub, transformers). The user's global
# cache at C:\Users\<u>\.cache\huggingface\ has had permission issues
# on this dev box (WinError 183 / Permission denied on `refs/main`),
# leaving the Whisper model in a half-downloaded state. A project-local
# cache sidesteps the broken global one and is writable per-user.
_HF_CACHE = (Path(__file__).resolve().parent.parent.parent / ".hf_cache")
_HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(_HF_CACHE)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# F5-TTS, tqdm, huggingface_hub, and friends spew progress to FD 1
# (stdout). The bridge protocol needs FD 1 to be JSON-only — a single
# rogue progress bar without a trailing `\n` can fill the pipe buffer
# and deadlock both processes (the Rust BufReader waits for `\n`, Python
# blocks on `write`). Solution: dup FD 1 once at startup and reroute the
# original FD 1 to FD 2 (stderr). Python's `sys.stdout` and any C-level
# `write(1, ...)` from ML libraries now land on stderr — inherited by
# Rust and captured by `tracing` / the test harness. The JSON bridge
# writes directly to the saved FD via `os.write` so it bypasses
# `sys.stdout` entirely.
_BRIDGE_FD = os.dup(1)
os.dup2(2, 1)


def _emit(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    os.write(_BRIDGE_FD, line.encode("utf-8"))


def _log(level: str, message: str) -> None:
    _emit({"log": {"level": level, "message": message}})


_F5_LOADED = False
_STT: Any = None
_WAKE_WORD: Any = None


def _ensure_f5() -> None:
    """Lazy-load F5-TTS on first tts_speak. ~30-60s warm-up on cold GPU."""
    global _F5_LOADED
    if _F5_LOADED:
        return
    from kernel.voice import tts_engine_f5

    tts_engine_f5.load_models()
    _F5_LOADED = True
    _log("info", "F5-TTS Russian loaded")


def _ensure_wake_word() -> Any:
    """Lazy-load OpenWakeWord on first wake_detect.

    The upstream package downloads/loads three ONNX models in sequence:
    melspectrogram → embedding → keyword classifier (`hey_jarvis_v0.1`
    and the other bundled keywords). Cold start on this dev box is
    ~10-20 s; steady-state inference is well under 100 ms on CPU.

    Reuses `kernel.voice.wake_word.WakeWordDetector` so the threshold
    + buffer + reset semantics match exactly what the Python pipeline
    used pre-Phase-3.
    """
    global _WAKE_WORD
    if _WAKE_WORD is not None:
        return _WAKE_WORD
    from kernel.voice.wake_word import WakeWordDetector

    _WAKE_WORD = WakeWordDetector(wake_word="jarvis")
    _WAKE_WORD.load()
    if not _WAKE_WORD.is_loaded:
        raise RuntimeError("OpenWakeWord failed to load — see kernel.voice.wake_word logs")
    _log("info", "OpenWakeWord loaded")
    return _WAKE_WORD


def _ensure_stt() -> Any:
    """Lazy-load Whisper (faster-whisper) on first stt_transcribe.

    `base` model on RTX-class GPU loads in ~3-5s. Falls back to CPU if
    CUDA isn't available; `kernel/voice/stt.py::SpeechToText` handles the
    detection.
    """
    global _STT
    if _STT is not None:
        return _STT
    from kernel.voice.stt import SpeechToText

    _STT = SpeechToText(model_size="base", device="auto")
    _STT.load()
    if not _STT.is_loaded:
        raise RuntimeError("Whisper failed to load — see kernel.voice.stt logs")
    _log("info", "Whisper STT loaded")
    return _STT


def _handle_tts_speak(args: dict[str, Any]) -> dict[str, Any]:
    """text → ruaccent → F5-TTS → base64 f32 LE waveform."""
    from kernel.voice import text_preprocessor, tts_engine_f5

    text = args["text"]
    accented = text_preprocessor.preprocess(text)
    _ensure_f5()
    waveform, sample_rate = tts_engine_f5.generate_audio(accented)
    audio_bytes = waveform.astype("float32").tobytes()
    return {
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
        "sample_rate": int(sample_rate),
        "duration_ms": int(len(waveform) / sample_rate * 1000),
    }


def _handle_stt_transcribe(args: dict[str, Any]) -> dict[str, Any]:
    """base64 i16 LE PCM → (resample to 16 kHz if needed) → faster-whisper.

    faster-whisper expects 16 kHz mono. We accept any input sample rate
    and resample server-side using `scipy.signal.resample_poly` (proper
    anti-alias filter — naive decimation in Rust produces aliasing that
    fools Whisper into detecting the wrong language).
    """
    import numpy as np
    from scipy.signal import resample_poly

    audio_b64 = args["audio_b64"]
    sample_rate = int(args.get("sample_rate", 16000))
    language = args.get("language")  # ISO 639-1 hint, e.g. "ru"; None to auto-detect
    raw = base64.b64decode(audio_b64)
    if len(raw) % 2 != 0:
        raise ValueError(f"audio_b64 length {len(raw)} not divisible by 2 (expected i16 LE)")
    samples_i16 = np.frombuffer(raw, dtype="<i2")
    audio_f32 = samples_i16.astype(np.float32) / 32768.0

    target_sr = 16000
    if sample_rate != target_sr:
        from math import gcd

        g = gcd(sample_rate, target_sr)
        up = target_sr // g
        down = sample_rate // g
        audio_f32 = resample_poly(audio_f32, up, down).astype(np.float32)

    stt = _ensure_stt()
    # Forward the language hint so faster-whisper skips its language
    # detection step. kernel.voice.stt.SpeechToText.transcribe doesn't
    # currently expose `language` — we call the underlying model
    # directly via _model. Falls back to its default behaviour if the
    # private attribute is missing.
    if language and stt._model is not None:
        import time
        t0 = time.perf_counter()
        segments, info = stt._model.transcribe(
            audio_f32,
            beam_size=5,
            language=language,
            vad_filter=True,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {
            "text": text,
            "language": info.language,
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }

    result = stt.transcribe(audio_f32, sample_rate=target_sr)
    return {
        "text": result.text,
        "language": result.language,
        "duration_ms": result.duration_ms,
    }


def _handle_wake_detect(args: dict[str, Any]) -> dict[str, Any]:
    """base64 i16 LE PCM → (resample to 16 kHz if needed) → openwakeword.

    OpenWakeWord requires 16 kHz mono input — its mel-spectrogram ONNX
    is hard-coded to that rate. We accept any sample rate and resample
    server-side via `scipy.signal.resample_poly` (proper anti-alias —
    naive Rust decimation produced gibberish for STT and would do the
    same here).
    """
    import numpy as np
    from scipy.signal import resample_poly

    audio_b64 = args["audio_b64"]
    sample_rate = int(args.get("sample_rate", 16000))
    threshold = float(args.get("threshold", 0.5))

    raw = base64.b64decode(audio_b64)
    if len(raw) % 2 != 0:
        raise ValueError(f"audio_b64 length {len(raw)} not divisible by 2 (expected i16 LE)")
    samples_i16 = np.frombuffer(raw, dtype="<i2")
    audio_f32 = samples_i16.astype(np.float32) / 32768.0

    target_sr = 16000
    if sample_rate != target_sr:
        from math import gcd

        g = gcd(sample_rate, target_sr)
        up = target_sr // g
        down = sample_rate // g
        audio_f32 = resample_poly(audio_f32, up, down).astype(np.float32)

    wake = _ensure_wake_word()
    # Apply caller-supplied threshold — instance var, only consulted
    # inside `.process()` at the score comparison. Reassign per-call so
    # the pipeline can tune dynamically without re-loading models.
    wake.threshold = threshold
    result = wake.process(audio_f32)

    return {
        "detected": bool(result.detected),
        "word": result.word,
        "confidence": float(result.confidence),
    }


def _handle_wake_reset(args: dict[str, Any]) -> dict[str, Any]:
    """Clear OpenWakeWord's internal LSTM state.

    No-op if the model hasn't been lazy-loaded yet — saves a 10-20 s
    cold start when the pipeline calls `reset()` defensively before
    the first detection.
    """
    if _WAKE_WORD is not None:
        _WAKE_WORD.reset()
    return {"ok": True}


def _handle(req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    args = req.get("args") or {}
    if op == "ping":
        return {"pong": True}
    if op == "tts_speak":
        return _handle_tts_speak(args)
    if op == "stt_transcribe":
        return _handle_stt_transcribe(args)
    if op == "wake_detect":
        return _handle_wake_detect(args)
    if op == "wake_reset":
        return _handle_wake_reset(args)
    raise ValueError(f"unknown op: {op!r}")


def main() -> int:
    _log("info", "tts_worker starting")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _log("error", f"bad json: {exc}")
            continue

        req_id = req.get("id")
        if req_id is None:
            _log("error", f"request missing id: {line!r}")
            continue

        try:
            result = _handle(req)
            _emit({"id": req_id, "result": result})
        except Exception as exc:  # noqa: BLE001 — bridge must not die on op error
            _emit(
                {
                    "id": req_id,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "trace": traceback.format_exc(),
                    },
                }
            )
    _log("info", "tts_worker stdin closed, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
