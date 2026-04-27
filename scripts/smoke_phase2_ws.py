"""Phase 2 smoke: connect to Rust /ws on :3006, listen for `voice.*` frames
for `LISTEN_SECONDS`, print every frame received and exit.

Pair with a separate `curl -X POST http://127.0.0.1:3005/voice/start` (run
shortly after this script starts) to verify the Python event bus → Rust
ingestion → WebSocket fan-out path.
"""

import asyncio
import json
import sys

import websockets

WS_URL = "ws://127.0.0.1:3006/ws"
LISTEN_SECONDS = 8.0


async def main() -> int:
    received: list[dict] = []
    try:
        async with websockets.connect(WS_URL) as ws:
            print(f"[ok] connected to {WS_URL}", flush=True)
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=LISTEN_SECONDS)
                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError:
                        frame = {"raw": raw}
                    print(f"[frame] {json.dumps(frame, ensure_ascii=False)}", flush=True)
                    received.append(frame)
            except TimeoutError:
                print(f"[done] listened {LISTEN_SECONDS}s, {len(received)} frames", flush=True)
    except Exception as exc:  # noqa: BLE001 — smoke script
        print(f"[err] {type(exc).__name__}: {exc}", flush=True)
        return 1

    if not received:
        print("[fail] no frames received during the listen window", flush=True)
        return 2
    voice = [f for f in received if str(f.get("type", "")).startswith("voice.")]
    if not voice:
        print(f"[warn] no voice.* frames; types seen: {sorted({f.get('type') for f in received})}", flush=True)
        return 3
    print(f"[pass] received {len(voice)} voice.* frame(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
