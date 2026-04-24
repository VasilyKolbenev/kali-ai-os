//! WebSocket endpoint.
//!
//! Each connection:
//!   - subscribes to the shared `EventBus`
//!   - spawns a send-task that forwards every bus event as a WsMessage
//!   - spawns a recv-task that parses client frames; `ui.command` frames
//!     are re-published on the bus; anything else is logged and ignored.
//!
//! On `RecvError::Lagged` the send-task drops the gap and keeps going —
//! matches Python's "no backfill on slow subscriber" semantics.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::State;
use axum::response::IntoResponse;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::broadcast::error::RecvError;
use tracing::{debug, info, warn, Instrument};

use crate::backend::event_bus::EventBus;
use crate::backend::models::{Event, WsMessage};

/// Monotonic per-process connection id so every WS subscriber can be
/// followed through the logs. Wraps at u64::MAX which never happens in
/// practice.
static SUB_COUNTER: AtomicU64 = AtomicU64::new(0);

pub async fn handler(
    ws: WebSocketUpgrade,
    State(bus): State<Arc<EventBus>>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, bus))
}

async fn handle_socket(socket: WebSocket, bus: Arc<EventBus>) {
    let sub_id = SUB_COUNTER.fetch_add(1, Ordering::Relaxed);
    let span = tracing::info_span!("ws_client", sub_id = sub_id);
    handle_socket_inner(socket, bus).instrument(span).await
}

async fn handle_socket_inner(socket: WebSocket, bus: Arc<EventBus>) {
    let (mut sender, mut receiver) = socket.split();
    let mut rx = bus.subscribe();
    info!(subscribers = bus.subscriber_count(), "WS client connected");

    let bus_for_recv = bus.clone();

    let send_task = tokio::spawn(async move {
        loop {
            match rx.recv().await {
                Ok(event) => {
                    let msg: WsMessage = (&event).into();
                    match serde_json::to_string(&msg) {
                        Ok(raw) => {
                            if sender.send(Message::Text(raw)).await.is_err() {
                                break;
                            }
                        }
                        Err(err) => {
                            warn!(?err, "serialise WS frame failed; dropping event");
                        }
                    }
                }
                Err(RecvError::Lagged(skipped)) => {
                    warn!(skipped, "WS subscriber lagged; continuing after gap");
                }
                Err(RecvError::Closed) => break,
            }
        }
    });

    let recv_task = tokio::spawn(async move {
        while let Some(frame) = receiver.next().await {
            let Ok(msg) = frame else { break };
            match msg {
                Message::Text(raw) => match serde_json::from_str::<WsMessage>(&raw) {
                    Ok(parsed) if parsed.kind == "ui.command" => {
                        bus_for_recv.publish(Event {
                            topic: "ui.command".to_string(),
                            source: "websocket".to_string(),
                            payload: parsed.data,
                            timestamp: chrono::Utc::now(),
                            correlation_id: uuid::Uuid::new_v4().to_string(),
                        });
                    }
                    Ok(other) => {
                        debug!(kind = %other.kind, "unhandled WS message kind");
                    }
                    Err(err) => {
                        debug!(?err, "malformed WS frame, ignoring");
                    }
                },
                Message::Close(_) => break,
                Message::Ping(_) | Message::Pong(_) | Message::Binary(_) => {
                    // tungstenite auto-handles Ping/Pong keepalive.
                }
            }
        }
    });

    tokio::select! {
        _ = send_task => {}
        _ = recv_task => {}
    }
    info!("WS client disconnected");
}
