"""WebSocket endpoint — extracted from kernel/main.py (T8).

Body is byte-identical to the pre-split closure (only ``@app.`` →
``@router.``); ``logger`` is the module logger.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from kernel.models import Event, WSMessage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    s = ws.app.state
    await ws.accept()
    s.ws_connections.append(ws)
    logger.info("WebSocket client connected (%d total)", len(s.ws_connections))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                msg = WSMessage(**data)
                if msg.type in ("ui.command", "voice.state", "voice.audio_stream"):
                    await s.event_bus.publish(
                        Event(
                            topic=msg.type,
                            source="websocket",
                            payload=msg.data,
                        )
                    )
                    # We don't need to ACK audio streams to save bandwidth
                    if msg.type == "ui.command":
                        await ws.send_json({"type": "ui.command", "data": {"status": "received"}})
                else:
                    await ws.send_json(
                        {"type": "error", "data": {"message": f"Unknown type: {msg.type}"}}
                    )
            except (json.JSONDecodeError, ValueError) as e:
                await ws.send_json({"type": "error", "data": {"message": str(e)}})
    except WebSocketDisconnect:
        s.ws_connections.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(s.ws_connections))
