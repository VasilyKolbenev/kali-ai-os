//! Internal event ingestion: POST /_internal/events.
//!
//! Python publishes every bus event here over HTTP so Rust can fan it out
//! to WebSocket clients. The endpoint is loopback-only — the `ConnectInfo`
//! extractor gives us the peer address; anything outside 127.0.0.0/8 and
//! ::1 is rejected with 403. The path prefix `_internal/` also marks it as
//! not part of the public UI contract (not added to `RUST_ENDPOINTS`, not
//! documented in API docs).

use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;

use axum::extract::{ConnectInfo, Json as ExtractJson, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;
use tracing::{debug, warn};

use crate::backend::event_bus::EventBus;
use crate::backend::models::Event;

#[tracing::instrument(skip_all, fields(topic = %event.topic, source = %event.source))]
pub async fn ingest(
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    State(bus): State<Arc<EventBus>>,
    ExtractJson(event): ExtractJson<Event>,
) -> Response {
    if !is_loopback(addr.ip()) {
        warn!(%addr, "rejected non-loopback ingestion");
        return (
            StatusCode::FORBIDDEN,
            Json(json!({ "error": "loopback_only" })),
        )
            .into_response();
    }
    let delivered = bus.publish(event);
    debug!(delivered, "ingested event");
    (
        StatusCode::ACCEPTED,
        Json(json!({ "delivered": delivered })),
    )
        .into_response()
}

fn is_loopback(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => v4.is_loopback(),
        IpAddr::V6(v6) => v6.is_loopback(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loopback_v4_accepted() {
        assert!(is_loopback("127.0.0.1".parse().unwrap()));
        assert!(is_loopback("127.1.2.3".parse().unwrap()));
    }

    #[test]
    fn loopback_v6_accepted() {
        assert!(is_loopback("::1".parse().unwrap()));
    }

    #[test]
    fn public_v4_rejected() {
        assert!(!is_loopback("8.8.8.8".parse().unwrap()));
        assert!(!is_loopback("192.168.1.1".parse().unwrap()));
    }
}
