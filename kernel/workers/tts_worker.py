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
from typing import Any

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


def _ensure_f5() -> None:
    """Lazy-load F5-TTS on first tts_speak. ~30-60s warm-up on cold GPU."""
    global _F5_LOADED
    if _F5_LOADED:
        return
    from kernel.voice import tts_engine_f5

    tts_engine_f5.load_models()
    _F5_LOADED = True
    _log("info", "F5-TTS Russian loaded")


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


def _handle(req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    args = req.get("args") or {}
    if op == "ping":
        return {"pong": True}
    if op == "tts_speak":
        return _handle_tts_speak(args)
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
