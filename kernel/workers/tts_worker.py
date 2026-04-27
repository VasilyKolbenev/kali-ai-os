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

import json
import sys
import traceback
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _log(level: str, message: str) -> None:
    _emit({"log": {"level": level, "message": message}})


def _handle(req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    if op == "ping":
        return {"pong": True}
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
