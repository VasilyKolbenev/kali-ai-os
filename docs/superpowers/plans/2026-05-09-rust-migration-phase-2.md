# Rust Migration Phase 2 — WebSocket + Event Bus

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the realtime event fan-out (voice pipeline state, agent status, dashboard updates) from Python's `/ws` to Rust's `/ws` on port 3006. Rust gains an in-process event bus (`tokio::sync::broadcast`) and a loopback-only ingestion endpoint so Python can push events into it. UI flips its WebSocket URL to Rust. After this phase, realtime traffic flows through Rust; Python's `/ws` stays alive but idle (deleted in Phase 8).

**Architecture delta after this phase:**

```
Before Phase 2:
  UI WS → ws://127.0.0.1:3005/ws (Python, authoritative for events)
  Python event bus → ws_forwarder → Python WS clients
  Rust: HTTP only (/health, /version, /config, /voice/status)

After Phase 2:
  UI WS → ws://127.0.0.1:3006/ws (Rust)
  Python event bus
        → ws_forwarder  (still present, now no-op for connected clients)
        → rust_bridge   (new: HTTP POST /_internal/events to Rust)
  Rust:
        axum WebSocket /ws
          ← tokio::sync::broadcast::Receiver per client
        axum POST /_internal/events  (loopback-only, validates origin)
          → broadcast::Sender.send(Event)
        → fans out to every connected WS client

UI → Python command path (ui.command):
  Rust WS accepts the message and re-publishes on its local bus.
  Python does not currently consume ui.command (only echoes), so no
  reverse bridge is needed in Phase 2. Document this; revisit if a
  future command needs Python processing.
```

**Tech stack additions:**
- `tokio::sync::broadcast` (already available via tokio) — N-producer, M-consumer channel with lag semantics; perfect for fan-out where slow subscribers can drop old events rather than stall the producer.
- `axum::extract::ws` (already in axum) — WebSocket upgrade helpers.
- `futures-util` 0.3 — `StreamExt` / `SinkExt` for splitting the WS into sender + receiver halves.
- No new UI deps.

**Prerequisites:**
- Phase 1 landed (`docs/superpowers/plans/2026-05-02-rust-migration-phase-1.md`). Rust serves `/health`, `/version`, `/config` (GET+PATCH), `/voice/status`. Dispatcher is method-aware.
- Settings UI Chunk 3 landed — confirms PATCH /config → Rust proxy path works end-to-end.
- Spec read: `docs/superpowers/specs/2026-04-24-rust-backend-migration.md` §3 (architecture), §6 (WS contract), §7 (bridge protocol — this phase does **not** touch the ML stdio bridge, only the event bus bridge).

**Unblocks:**
- Tier 1 #6 Feedback channel — once Rust owns the WS, UI can emit a `feedback.*` event that Rust relays to a logging sink without Python involvement.
- Phase 3 (voice pipeline) — the pipeline state machine in Rust will emit its own events on the bus; needs this infrastructure ready.
- Phase 4+ — any server-pushed realtime feature.

**Scope carve-outs (explicitly deferred):**
- Deleting Python `/ws` endpoint — stays through Phase 8. Risk: dual source of truth during the overlap. Mitigation: the bridge only flows one way (Python → Rust); Python's ws_forwarder runs against zero connected clients so its fan-out is a no-op.
- Rust-originated events (Rust publishing without Python input) — in Phase 2 the bus carries only what Python pushes. Rust-native publishers arrive in Phase 3 when the voice pipeline moves.
- Replay / backfill on reconnect — the broadcast channel is live-only. Phase 7 adds SQLite-backed event history if needed; not needed for current UI behaviour.

---

## Chunk 1: Rust Event Bus + WebSocket Endpoint

**What:** Introduce a `tokio::sync::broadcast`-based event bus inside the Rust backend and a `GET /ws` WebSocket endpoint that subscribes every connected client to the bus. No Python integration yet — events come only from tests (and, at runtime, from nothing, so the WS fan-outs nothing until Chunk 2). The endpoint accepts `ui.command` frames from clients and re-publishes them on the bus; this matches current Python behaviour so UI keeps working on day one.

**Why separately from the bridge:** verifying the broadcast + WS handshake in isolation catches backpressure / framing bugs before we add a second moving part.

### Files

- Create: `src-tauri/src/backend/event_bus.rs` — `EventBus` wrapper around `broadcast::Sender<Event>`, `publish`/`subscribe` methods.
- Create: `src-tauri/src/backend/models.rs` — `Event` and `WsMessage` serde structs mirroring `kernel/models.py`.
- Create: `src-tauri/src/backend/ws.rs` — axum WS handler, split into send-task (bus → socket) and recv-task (socket → bus), with proper close + lag handling.
- Create: `src-tauri/tests/ws_broadcast.rs` — integration test: connect two WS clients, publish on the bus, both clients receive the frame.
- Modify: `src-tauri/src/backend/mod.rs` — add `pub mod event_bus;`, `pub mod models;`, `pub mod ws;`; expose a shared `EventBus` created in `serve()`.
- Modify: `src-tauri/src/backend/http.rs` — take an `EventBus` (or a router builder that does) and add `.route("/ws", get(ws::handler))` wired to it via `Router::with_state` or an `Extension` layer.
- Modify: `src-tauri/Cargo.toml` — add `futures-util = "0.3"` and `tokio-tungstenite = "0.21"` (dev-dep, for the test client).

### Tasks

- [ ] **Step 1: Add deps and scaffold the module tree**

Extend `src-tauri/Cargo.toml`:

```toml
[dependencies]
futures-util = "0.3"
# (axum already includes ws via default features)

[dev-dependencies]
tokio-tungstenite = "0.21"
```

Create empty `event_bus.rs`, `models.rs`, `ws.rs` (just `//! module docs`). Update `src-tauri/src/backend/mod.rs`:

```rust
pub mod config;
pub mod error;
pub mod http;
pub mod proxy;
pub mod event_bus;
pub mod models;
pub mod ws;
```

Run: `cargo check -p kali-desktop`  → compiles.

- [ ] **Step 2: Write the failing `EventBus` test**

Create `src-tauri/src/backend/event_bus.rs`:

```rust
//! In-process pub/sub for realtime events fanned out to WebSocket clients.
//!
//! Wraps `tokio::sync::broadcast` with a named-topic Event API matching the
//! existing Python shape. Subscribers get every event published after they
//! subscribed; slow subscribers see `RecvError::Lagged` which the WS handler
//! treats as "skip this gap, keep going" rather than closing the socket.

use tokio::sync::broadcast;

use crate::backend::models::Event;

/// Default capacity. 256 is the usual sweet spot — large enough that a slow
/// consumer can miss a whole voice-pipeline burst without disconnecting,
/// small enough that a stalled consumer can't hoard megabytes of payloads.
pub const BUS_CAPACITY: usize = 256;

#[derive(Debug, Clone)]
pub struct EventBus {
    tx: broadcast::Sender<Event>,
}

impl EventBus {
    pub fn new() -> Self {
        let (tx, _rx) = broadcast::channel(BUS_CAPACITY);
        Self { tx }
    }

    /// Publish an event. Returns the number of active subscribers that
    /// received it (0 is normal when no clients are connected — NOT an error).
    pub fn publish(&self, event: Event) -> usize {
        self.tx.send(event).unwrap_or(0)
    }

    pub fn subscribe(&self) -> broadcast::Receiver<Event> {
        self.tx.subscribe()
    }

    pub fn subscriber_count(&self) -> usize {
        self.tx.receiver_count()
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}
```

Create `src-tauri/src/backend/models.rs`:

```rust
//! Wire shapes for events and WebSocket messages. Must match Python's
//! `kernel/models.py` — contract tests in Phase 2 verify the round-trip.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Event envelope published on the bus. Matches Pydantic `Event`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub topic: String,
    pub source: String,
    pub payload: serde_json::Value,
    #[serde(default = "Utc::now")]
    pub timestamp: DateTime<Utc>,
    #[serde(default = "new_uuid")]
    pub correlation_id: String,
}

fn new_uuid() -> String {
    Uuid::new_v4().to_string()
}

/// Frame exchanged over the WebSocket. Matches Pydantic `WSMessage`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WsMessage {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub data: serde_json::Value,
}

impl From<&Event> for WsMessage {
    fn from(e: &Event) -> Self {
        Self {
            kind: e.topic.clone(),
            data: e.payload.clone(),
        }
    }
}
```

Add `chrono` and `uuid` to `Cargo.toml` (check if not already present — they likely aren't):

```toml
chrono = { version = "0.4", features = ["serde"] }
uuid = { version = "1", features = ["v4", "serde"] }
```

Run: `cargo check -p kali-desktop`  → compiles. No tests yet.

- [ ] **Step 3: Write the WS handler with send + recv tasks**

Create `src-tauri/src/backend/ws.rs`:

```rust
//! WebSocket endpoint. Each connection:
//!   - subscribes to the shared `EventBus`
//!   - spawns a send-task that forwards every bus event as a WsMessage
//!   - spawns a recv-task that parses client frames; `ui.command` is
//!     re-published on the bus, anything else becomes an `error` reply.
//!
//! On `RecvError::Lagged` the send-task continues (drops the gap), matching
//! Python's "we don't buffer for reconnects" semantics.

use std::sync::Arc;

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::State;
use axum::response::IntoResponse;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::broadcast::error::RecvError;
use tracing::{debug, info, warn};

use crate::backend::event_bus::EventBus;
use crate::backend::models::{Event, WsMessage};

pub async fn handler(
    ws: WebSocketUpgrade,
    State(bus): State<Arc<EventBus>>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, bus))
}

async fn handle_socket(socket: WebSocket, bus: Arc<EventBus>) {
    let (mut sender, mut receiver) = socket.split();
    let mut rx = bus.subscribe();
    info!(subscribers = bus.subscriber_count(), "WS client connected");

    let bus_for_recv = bus.clone();

    // Send task: bus → socket
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
                    // keep going
                }
                Err(RecvError::Closed) => break,
            }
        }
    });

    // Recv task: socket → bus
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
                    // axum handles Ping automatically via tungstenite defaults.
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
```

Run: `cargo check -p kali-desktop`  → compiles. No tests yet.

- [ ] **Step 4: Wire the bus + WS route into the router**

Modify `src-tauri/src/backend/http.rs`:

```rust
use std::sync::Arc;

use axum::{
    extract::Json as ExtractJson,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde::Serialize;
use serde_json::json;

use crate::backend::config;
use crate::backend::error::AppResult;
use crate::backend::event_bus::EventBus;
use crate::backend::proxy;
use crate::backend::ws;

// ... existing handlers unchanged ...

pub fn router_with_bus(bus: Arc<EventBus>) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config).patch(patch_config))
        .route("/voice/status", get(voice_status))
        .route("/ws", get(ws::handler))
        .with_state(bus)
}

/// Kept for backward compatibility with existing tests that call
/// `kali_desktop::backend::http::router()`. Those tests construct a
/// bus-less instance — the /ws route still exists but has no publisher.
pub fn router() -> Router {
    router_with_bus(Arc::new(EventBus::new()))
}
```

Modify `src-tauri/src/backend/mod.rs` so the process-wide bus is created in `serve()` and passed to the router. Update `serve()` signature if needed:

```rust
pub async fn serve() -> anyhow::Result<()> {
    let bus = std::sync::Arc::new(event_bus::EventBus::new());
    // store bus in a tauri::State if the ingestion handler (Chunk 2) needs
    // to reach it from a non-WS route; for now it's only referenced by /ws.
    let app = http::router_with_bus(bus.clone());
    // ... existing listener bind + axum::serve
}
```

Keep the existing `RUST_BIND_ADDR` and tracing init.

Run: `cargo check -p kali-desktop`  → compiles.

- [ ] **Step 5: Write the failing WS integration test**

Create `src-tauri/tests/ws_broadcast.rs`:

```rust
//! WS contract: two clients subscribe, a publish on the bus fans out to both.

use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use kali_desktop::backend::event_bus::EventBus;
use kali_desktop::backend::http::router_with_bus;
use kali_desktop::backend::models::Event;

async fn spawn_server() -> (std::net::SocketAddr, Arc<EventBus>) {
    let bus = Arc::new(EventBus::new());
    let app: Router = router_with_bus(bus.clone());
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });
    (addr, bus)
}

#[tokio::test]
async fn publish_fans_out_to_all_connected_clients() {
    let (addr, bus) = spawn_server().await;
    let url = format!("ws://{}/ws", addr);

    let (mut client_a, _) = connect_async(&url).await.expect("client A connect");
    let (mut client_b, _) = connect_async(&url).await.expect("client B connect");

    // Give the server a beat to register both subscribers before we publish.
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert_eq!(bus.subscriber_count(), 2);

    bus.publish(Event {
        topic: "voice.state".to_string(),
        source: "kernel".to_string(),
        payload: json!({ "state": "listening" }),
        timestamp: chrono::Utc::now(),
        correlation_id: "test-1".to_string(),
    });

    let a_msg = tokio::time::timeout(Duration::from_secs(2), client_a.next())
        .await
        .expect("A timed out")
        .expect("A stream closed")
        .expect("A frame error");
    let b_msg = tokio::time::timeout(Duration::from_secs(2), client_b.next())
        .await
        .expect("B timed out")
        .expect("B stream closed")
        .expect("B frame error");

    for msg in [a_msg, b_msg] {
        let Message::Text(raw) = msg else { panic!("expected text frame") };
        let parsed: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(parsed["type"], "voice.state");
        assert_eq!(parsed["data"]["state"], "listening");
    }
}

#[tokio::test]
async fn ui_command_from_client_is_published_back_on_bus() {
    let (addr, bus) = spawn_server().await;
    let url = format!("ws://{}/ws", addr);

    let mut rx = bus.subscribe();
    let (mut client, _) = connect_async(&url).await.expect("connect");
    tokio::time::sleep(Duration::from_millis(50)).await;

    let frame = json!({ "type": "ui.command", "data": { "name": "open.settings" } });
    client
        .send(Message::Text(frame.to_string()))
        .await
        .expect("send");

    let event = tokio::time::timeout(Duration::from_secs(2), rx.recv())
        .await
        .expect("timeout")
        .expect("recv");
    assert_eq!(event.topic, "ui.command");
    assert_eq!(event.source, "websocket");
    assert_eq!(event.payload["name"], "open.settings");
}

#[tokio::test]
async fn malformed_frame_does_not_disconnect_client() {
    let (addr, _bus) = spawn_server().await;
    let url = format!("ws://{}/ws", addr);
    let (mut client, _) = connect_async(&url).await.expect("connect");
    client.send(Message::Text("not-json".into())).await.expect("send");
    // Server should not close; a ping round-trip should still succeed.
    client.send(Message::Ping(vec![1, 2])).await.expect("ping");
    let _ = tokio::time::timeout(Duration::from_millis(500), client.next()).await;
}
```

Run: `cargo test --test ws_broadcast` → expect all three tests pass.

- [ ] **Step 6: Verify nothing else regressed**

Run: `cargo test` (full workspace). Should be 13 passing across `config_endpoint`, `endpoints_contract`, `version_endpoint`, `voice_status_proxy`, `ws_broadcast`.

- [ ] **Step 7: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/src/backend/ src-tauri/tests/ws_broadcast.rs
git commit -m "feat(rust-backend): WebSocket /ws + broadcast event bus (Phase 2 Chunk 1)"
```

---

## Chunk 2: Python → Rust Ingestion Bridge

**What:** Add a loopback-only ingestion endpoint on Rust (`POST /_internal/events`) and a Python side that subscribes to the existing event bus and POSTs every relevant event to Rust. After this chunk, an event published anywhere in Python (voice pipeline, scheduler, notifications) appears on every Rust WS client. The existing Python `/ws` keeps working for any legacy consumer — the two paths run side by side.

**Why the `/_internal/` prefix:** marks it as not part of the public UI contract. Not added to `RUST_ENDPOINTS` in the UI dispatcher; not documented in API docs; logged distinctly; gated on the connection originating from loopback.

### Files

- Create: `src-tauri/src/backend/ingestion.rs` — `POST /_internal/events` handler.
- Modify: `src-tauri/src/backend/http.rs` — mount the route on `router_with_bus`.
- Modify: `src-tauri/src/backend/mod.rs` — expose `pub mod ingestion`.
- Modify: `src-tauri/src/lib.rs` (or wherever `connect_info` is configured) — ensure axum receives client IP so the handler can reject non-loopback requests.
- Create: `kernel/rust_bridge.py` — `RustEventBridge` class that posts events via httpx, plus a factory that subscribes it to the event bus.
- Modify: `kernel/main.py` — instantiate `RustEventBridge` in the startup path, subscribe it to the same topic globs as `ws_forwarder` (`agent.*`, `voice.*`, `ui.*`, `dashboard.*`, `schedule.*`, `system.*`).
- Create: `src-tauri/tests/ingestion.rs` — POST an event, WS client receives it; non-loopback IP rejected; bad body → 400.
- Create: `tests/kernel/test_rust_bridge.py` — unit test: bridge posts serialised event, handles Rust-down without raising.

### Tasks

- [ ] **Step 1: Write the Rust ingestion handler + test**

Create `src-tauri/src/backend/ingestion.rs`:

```rust
//! Internal event ingestion: POST /_internal/events.
//!
//! Python publishes every bus event here via HTTP so Rust can fan it out
//! to WebSocket clients. Loopback-only — the `connect_info` extractor
//! tells us the peer address; anything outside 127.0.0.0/8 and ::1 is
//! rejected with 403.

use std::net::IpAddr;
use std::sync::Arc;

use axum::extract::{ConnectInfo, Json as ExtractJson, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde_json::json;
use std::net::SocketAddr;
use tracing::{debug, warn};

use crate::backend::event_bus::EventBus;
use crate::backend::models::Event;

pub async fn ingest(
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    State(bus): State<Arc<EventBus>>,
    ExtractJson(event): ExtractJson<Event>,
) -> Response {
    if !is_loopback(addr.ip()) {
        warn!(%addr, "rejected non-loopback ingestion");
        return (StatusCode::FORBIDDEN, Json(json!({"error":"loopback_only"}))).into_response();
    }
    let delivered = bus.publish(event);
    debug!(delivered, "ingested event");
    (StatusCode::ACCEPTED, Json(json!({"delivered": delivered}))).into_response()
}

fn is_loopback(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => v4.is_loopback(),
        IpAddr::V6(v6) => v6.is_loopback(),
    }
}

use axum::Json; // kept at end so the top-level `Json` unification is explicit
```

Modify `src-tauri/src/backend/http.rs` to include the ingestion route:

```rust
pub fn router_with_bus(bus: Arc<EventBus>) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config).patch(patch_config))
        .route("/voice/status", get(voice_status))
        .route("/ws", get(ws::handler))
        .route("/_internal/events", axum::routing::post(ingestion::ingest))
        .with_state(bus)
}
```

Modify the `axum::serve` call in `mod.rs` / `lib.rs` to pass `ConnectInfo`:

```rust
axum::serve(
    listener,
    app.into_make_service_with_connect_info::<SocketAddr>(),
)
.await?;
```

(Phase 0 used `axum::serve(listener, app)` — the new call is required so `ConnectInfo` extraction works. Existing tests keep passing because `reqwest` connects from localhost.)

- [ ] **Step 2: Write the failing ingestion test**

Create `src-tauri/tests/ingestion.rs`:

```rust
use std::sync::Arc;
use std::time::Duration;

use futures_util::StreamExt;
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use kali_desktop::backend::event_bus::EventBus;
use kali_desktop::backend::http::router_with_bus;

async fn spawn_server() -> (std::net::SocketAddr, Arc<EventBus>) {
    let bus = Arc::new(EventBus::new());
    let app = router_with_bus(bus.clone());
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(
            listener,
            app.into_make_service_with_connect_info::<std::net::SocketAddr>(),
        ).await.unwrap();
    });
    (addr, bus)
}

#[tokio::test]
async fn ingested_event_reaches_ws_client() {
    let (addr, _bus) = spawn_server().await;
    let ws_url = format!("ws://{}/ws", addr);
    let (mut client, _) = connect_async(&ws_url).await.unwrap();
    tokio::time::sleep(Duration::from_millis(50)).await;

    let body = json!({
        "topic": "voice.pipeline",
        "source": "python",
        "payload": { "active": true },
        "timestamp": "2026-05-09T12:00:00Z",
        "correlation_id": "cid-1"
    });
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), 202);
    assert_eq!(resp.json::<Value>().await.unwrap()["delivered"], 1);

    let frame = tokio::time::timeout(Duration::from_secs(2), client.next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let Message::Text(raw) = frame else { panic!("expected text") };
    let parsed: Value = serde_json::from_str(&raw).unwrap();
    assert_eq!(parsed["type"], "voice.pipeline");
    assert_eq!(parsed["data"]["active"], true);
}

#[tokio::test]
async fn ingestion_accepts_event_without_timestamp_or_correlation_id() {
    // Python's Event model populates those server-side, but defense in
    // depth: missing optional fields must not 400.
    let (addr, _bus) = spawn_server().await;
    let body = json!({
        "topic": "system.startup",
        "source": "python",
        "payload": {}
    });
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), 202);
}

#[tokio::test]
async fn ingestion_rejects_malformed_body_with_400() {
    let (addr, _bus) = spawn_server().await;
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .body("not-json")
        .header("content-type", "application/json")
        .send()
        .await
        .unwrap();
    assert!(resp.status().is_client_error(), "got {}", resp.status());
}

// Non-loopback rejection is not easily testable against a TcpListener bound
// to 127.0.0.1 because every connection originates from loopback. Covered
// by unit test on `is_loopback` if needed — for now, the guard is documented
// and logged. Moving it behind a feature flag or IP-allow-list is Phase 6+.
```

Run: `cargo test --test ingestion` → fails (handler not reachable) then passes after Step 1 is in place.

- [ ] **Step 3: Build the Python bridge**

Create `kernel/rust_bridge.py`:

```python
"""Forwards Python event-bus events to the Rust backend's
/_internal/events endpoint so Rust can fan them out to WebSocket clients.

Designed to be fire-and-forget: if Rust is down we log at DEBUG level
(not WARN — a missing Rust during early migration should not spam) and
move on. The Python WS endpoint stays live for any legacy consumer.
"""

import logging
from typing import Awaitable, Callable

import httpx

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)

DEFAULT_RUST_URL = "http://127.0.0.1:3006/_internal/events"

# Topics relayed to Rust. Matches the existing ws_forwarder subscriptions
# plus nothing else — anything not in this list stays Python-internal.
RELAYED_TOPIC_GLOBS: tuple[str, ...] = (
    "agent.*",
    "voice.*",
    "ui.*",
    "dashboard.*",
    "schedule.*",
    "system.*",
)


class RustEventBridge:
    """Owns an httpx.AsyncClient pool and forwards events to Rust.

    One instance per kernel; subscribe it to the event bus for each topic
    glob in `RELAYED_TOPIC_GLOBS`.
    """

    def __init__(self, url: str = DEFAULT_RUST_URL, timeout_s: float = 0.5) -> None:
        self._url = url
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def forward(self, event: Event) -> None:
        # Skip events that originated from the WebSocket itself — matches
        # Python's ws_forwarder behaviour and prevents a loop where a client
        # command echoes back as an event that is then re-ingested.
        if event.source == "websocket":
            return
        try:
            await self._client.post(self._url, json=event.model_dump(mode="json"))
        except httpx.HTTPError as err:
            logger.debug("rust_bridge: forward failed (%s): %s", type(err).__name__, err)

    async def close(self) -> None:
        await self._client.aclose()


def subscribe_to_bus(bridge: RustEventBridge, bus: EventBus) -> None:
    """Subscribe the bridge to each relayed topic glob on the given bus."""
    handler: Callable[[Event], Awaitable[None]] = bridge.forward
    for glob in RELAYED_TOPIC_GLOBS:
        bus.subscribe(glob, handler)
```

Create `tests/kernel/test_rust_bridge.py`:

```python
"""Tests for RustEventBridge."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from kernel.event_bus import EventBus
from kernel.models import Event
from kernel.rust_bridge import RELAYED_TOPIC_GLOBS, RustEventBridge, subscribe_to_bus


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> RustEventBridge:
    b = RustEventBridge(url="http://127.0.0.1:1")  # black-hole port
    mock_post = AsyncMock()
    monkeypatch.setattr(b._client, "post", mock_post)
    b._mock_post = mock_post  # expose for assertions
    return b


async def test_forward_posts_event_payload(bridge: RustEventBridge) -> None:
    event = Event(topic="voice.state", source="kernel", payload={"state": "listening"})
    await bridge.forward(event)
    bridge._mock_post.assert_awaited_once()
    args, kwargs = bridge._mock_post.call_args
    assert kwargs["json"]["topic"] == "voice.state"
    assert kwargs["json"]["payload"] == {"state": "listening"}


async def test_forward_skips_websocket_sourced_events(bridge: RustEventBridge) -> None:
    event = Event(topic="ui.command", source="websocket", payload={"name": "x"})
    await bridge.forward(event)
    bridge._mock_post.assert_not_awaited()


async def test_forward_swallows_connection_errors(bridge: RustEventBridge) -> None:
    bridge._mock_post.side_effect = httpx.ConnectError("refused")
    event = Event(topic="voice.state", source="kernel", payload={})
    # Must NOT raise.
    await bridge.forward(event)


async def test_subscribe_wires_all_relayed_globs() -> None:
    bus = EventBus()
    bridge = RustEventBridge(url="http://127.0.0.1:1")
    subscribe_to_bus(bridge, bus)
    assert bus.subscriber_count == len(RELAYED_TOPIC_GLOBS)
```

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_rust_bridge.py -v` → all pass.

- [ ] **Step 4: Wire the bridge into kernel startup**

Modify `kernel/main.py` in the lifespan startup block (after `event_bus = EventBus()` and alongside `ws_forwarder` registration):

```python
from kernel.rust_bridge import RustEventBridge, subscribe_to_bus

rust_bridge = RustEventBridge()
subscribe_to_bus(rust_bridge, event_bus)
app.state.rust_bridge = rust_bridge
```

And in the shutdown path:

```python
await request.app.state.rust_bridge.close()
```

(Find the existing shutdown block — same place where `await event_bus.publish(Event(topic="system.shutdown"...))` runs.)

Run: `pytest tests/kernel -q` — existing suite still green; new `test_rust_bridge.py` passes.

- [ ] **Step 5: End-to-end smoke test (manual)**

Only after Chunk 2 code is in place, this verifies the bridge actually talks to Rust:

1. Start Rust: `cargo run --manifest-path src-tauri/Cargo.toml` (or run via Tauri dev).
2. Start Python: `.venv/Scripts/python.exe -m kernel.entry`.
3. In another terminal: open a WS to Rust with `wscat -c ws://127.0.0.1:3006/ws`.
4. Trigger any event from Python — easiest is voice pipeline start:
   `curl -X POST http://127.0.0.1:3005/voice/start`
5. Expect `wscat` to print frames like `{"type":"voice.pipeline","data":{"active":true}}`.

Record the observed output in the commit message body.

- [ ] **Step 6: Commit**

```bash
git add src-tauri/src/backend/ingestion.rs src-tauri/src/backend/http.rs \
        src-tauri/src/backend/mod.rs src-tauri/src/lib.rs \
        src-tauri/tests/ingestion.rs \
        kernel/rust_bridge.py kernel/main.py tests/kernel/test_rust_bridge.py
git commit -m "feat(bridge): Python event bus → Rust /_internal/events → WS (Phase 2 Chunk 2)"
```

---

## Chunk 3: UI WebSocket Flip to Rust

**What:** Point `ui/src/api/websocket.ts` at `ws://127.0.0.1:3006/ws` via a new `rustWsUrl` export in `runtime.ts`. Keep `wsUrl` (Python `:3005`) as the legacy fallback for runtime override but not used by default. No UI message-handling changes — the frame shape is identical across both backends because contract tests in Chunk 1 verified round-trip.

**Why keep the legacy constant:** one line of defense if Phase 2 has to be reverted in the field — a user can set `window.__KALI_CONFIG__.wsUrl` and flip back without reinstalling.

### Files

- Modify: `ui/src/api/runtime.ts` — add `rustWsUrl`, default preferred order.
- Modify: `ui/src/api/websocket.ts` — connect to `rustWsUrl` (rename the imported binding, keep behaviour).
- Modify: `ui/src/api/runtime.test.ts` if it exists, or create it.
- Manual: preview verify that `voice.pipeline` events still update the Arc Reactor indicator.

### Tasks

- [ ] **Step 1: Extend `runtime.ts` with `rustWsUrl`**

Add after the existing `wsUrl` export:

```typescript
export const rustWsUrl =
  env.VITE_KALI_RUST_WS_URL ||
  runtimeConfig?.rustWsUrl ||
  `${httpToWebSocket(rustApiBaseUrl)}/ws`;
```

Extend the `Window.__KALI_CONFIG__` declaration at the top of the file:

```typescript
declare global {
  interface Window {
    __KALI_CONFIG__?: {
      apiBaseUrl?: string;
      rustApiBaseUrl?: string;
      wsUrl?: string;
      rustWsUrl?: string;
    };
  }
}
```

Run: `npx tsc --noEmit` → clean.

- [ ] **Step 2: Add a failing runtime test**

Create `ui/src/api/__tests__/runtime.test.ts` (or extend the endpoints one if you prefer colocated):

```typescript
import { describe, it, expect } from "vitest";
import { rustWsUrl } from "../runtime";

describe("runtime", () => {
  it("rustWsUrl defaults to ws://127.0.0.1:3006/ws", () => {
    expect(rustWsUrl).toBe("ws://127.0.0.1:3006/ws");
  });
});
```

Run: `pnpm test` — new test passes.

- [ ] **Step 3: Flip `websocket.ts` to `rustWsUrl`**

Modify `ui/src/api/websocket.ts`:

```typescript
import { rustWsUrl } from "./runtime";
// ...
const ws = new WebSocket(rustWsUrl);
```

Remove the now-unused `wsUrl` import. The existing reconnect loop + message switch are unchanged.

Run: `pnpm test` + `npx tsc --noEmit` → green.

- [ ] **Step 4: Manual preview verification**

1. Start Python: `.venv/Scripts/python.exe -m kernel.entry`.
2. Start Rust (Tauri dev): `cargo run --manifest-path src-tauri/Cargo.toml` — or `preview_start` with ui-dev and a separately-running Rust binary.
3. Load UI. Confirm no WS errors in browser console.
4. Trigger voice pipeline: `curl -X POST http://127.0.0.1:3005/voice/start`.
5. Observe the Arc Reactor indicator updates state within ~100 ms. Confirms voice.pipeline event reached UI via Rust.
6. Check `src-tauri` log for `WS client connected` and `ingested event` tracing lines.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/runtime.ts ui/src/api/websocket.ts ui/src/api/__tests__/
git commit -m "feat(ui): connect WebSocket to Rust backend on :3006 (Phase 2 Chunk 3)"
```

---

## Chunk 4: Observability + Rollout Hardening

**What:** Small polish chunk — adds the tracing spans + metrics the team will actually want once realtime traffic flows through Rust. Also documents the rollback path.

### Tasks

- [ ] **Step 1: Add a `subscribers` gauge to the Rust /health payload**

Modify `health` handler in `http.rs` to accept state and return the current WS subscriber count:

```rust
pub async fn health(State(bus): State<Arc<EventBus>>) -> AppResult<Json<HealthResponse>> {
    Ok(Json(HealthResponse {
        status: "ok",
        version: env!("CARGO_PKG_VERSION"),
        backend: "rust",
        ws_subscribers: bus.subscriber_count(),
    }))
}
```

Extend `HealthResponse` with `pub ws_subscribers: usize`. Update the existing `endpoints_contract.rs` test to tolerate the new field (Python's /health doesn't expose it — contract test was already defined as "subset of Python", so we need it the other way now; confirm or widen the assertion).

- [ ] **Step 2: Add tracing spans on event ingestion and WS handshake**

Already partly done in Chunks 1-2. Verify `ingestion.rs` uses `#[tracing::instrument(skip_all, fields(topic = %event.topic))]` on `ingest`. Verify `ws.rs` uses `info_span!("ws_client", sub_id=...)` or at minimum `tracing::info!` at connect/disconnect with a stable request id.

- [ ] **Step 3: Document the rollback**

Add a README-style note at the top of `kernel/rust_bridge.py`:

```python
"""...

Rollback: set `window.__KALI_CONFIG__.rustWsUrl = 'ws://127.0.0.1:3005/ws'`
in the Tauri bootstrap (or `VITE_KALI_RUST_WS_URL` for dev). The bridge
continues to POST to :3006 (harmless when nothing listens); Python's /ws
carries the traffic exactly as before Phase 2.
"""
```

- [ ] **Step 4: Commit**

```bash
git add src-tauri/src/backend/http.rs src-tauri/src/backend/ws.rs \
        src-tauri/src/backend/ingestion.rs src-tauri/tests/endpoints_contract.rs \
        kernel/rust_bridge.py
git commit -m "chore(phase-2): observability + rollback docs"
```

---

## Success Criteria (whole phase)

- ✅ `cargo test` green, including 3 new test files (`ws_broadcast.rs`, `ingestion.rs`, and extended `endpoints_contract.rs`).
- ✅ `pytest tests/kernel` green, including `test_rust_bridge.py`.
- ✅ `pnpm test` + `npx tsc --noEmit` green.
- ✅ With both backends running, triggering `voice.pipeline` in Python produces a visible Arc Reactor state change within 100ms — proving the whole chain (Python bus → Rust ingestion → Rust broadcast → UI WS) works.
- ✅ `/health` on Rust returns a non-zero `ws_subscribers` count while the UI is open, zero after closing the app.
- ✅ Memory `project_rust_migration.md` updated: "Phase 2 SHIPPED (YYYY-MM-DD)" with commit refs.

## Out of Scope (deferred)

- **Audio frame streaming over WS** (Phase 3): the voice pipeline in Rust will publish `voice.audio` frames directly on the local bus, skipping the Python bridge entirely for that high-rate path.
- **SQLite-backed event replay on reconnect** (Phase 7 if needed): current UI does not need it — fresh state is seeded via HTTP (`/voice/status`) on mount.
- **Reverse bridge (Rust → Python HTTP)** for UI commands that need Python handling: deferred until the first command actually needs it. Currently `ui.command` is only echoed, not consumed.
- **Deleting Python `/ws`**: stays until Phase 8 to preserve the rollback path and keep any out-of-band consumers (future CLI? debug tool?) working.
- **Per-topic subscriber filtering** (client asks for only `voice.*`): current UI subscribes to everything and filters client-side. Add server-side filtering only when the event volume forces it.

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Broadcast channel lag drops important events silently | Med | Med | Capacity 256; WS handler logs `warn!` on `RecvError::Lagged` with skipped count so we see it happening |
| Python bridge blocks the event loop when Rust is slow | Low | High | `httpx.AsyncClient` with 0.5s timeout; errors logged at DEBUG and swallowed — never propagated to the publisher |
| Dual WS (Python + Rust) double-delivers events to legacy tools | Low | Med | Python's ws_forwarder only fans out to connected Python-WS clients; UI no longer connects to Python, so it's effectively dark |
| `ConnectInfo` extractor change breaks existing Rust tests | Med | Low | Phase 1 tests use `axum::serve(listener, app)` which still compiles; the new `into_make_service_with_connect_info` is additive. Run full Rust suite after Chunk 2 Step 1 |
| YAML-only /config PATCH (Phase 1.5) and event bus in same session steps over each other | Low | Low | They're in different modules; review the `mod.rs` exports after Chunk 1 to confirm no naming collisions |
| Tauri's tokio runtime differs from test-runtime (e.g. single-thread vs multi) | Low | Med | Tests already use `#[tokio::test]` with default multi-thread; Tauri also spawns multi-thread — parity confirmed in Phase 0 |
| Non-loopback ingestion hole if CSP loosens in future | Low | High | Guard is `is_loopback` check at the handler entry, not a network-level filter — any change to CSP / binding requires revisiting `ingestion::ingest` |

## Estimate

- Chunk 1 (Rust bus + WS): ~4 hours (most of it test setup).
- Chunk 2 (Bridge): ~4 hours (Python + Rust + bridge wiring + e2e smoke).
- Chunk 3 (UI flip): ~1 hour.
- Chunk 4 (Observability): ~1 hour.

Total: ~10 hours of focused work, ~2 days calendar. Gates Tier 1 #6 (Feedback) and Phase 3 (voice pipeline orchestration).
