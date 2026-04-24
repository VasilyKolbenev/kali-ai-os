use std::sync::Arc;

use axum::{
    extract::{Json as ExtractJson, State},
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
use crate::backend::ingestion;
use crate::backend::proxy;
use crate::backend::ws;

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub version: &'static str,
    pub backend: &'static str,
    /// Number of WebSocket clients currently subscribed to the broadcast
    /// bus. Useful signal that the UI is actually connected to Rust — zero
    /// with a running app means the UI is misconfigured or Phase 2 has
    /// been rolled back via `rustWsUrl`.
    pub ws_subscribers: usize,
}

pub async fn health(State(bus): State<Arc<EventBus>>) -> AppResult<Json<HealthResponse>> {
    Ok(Json(HealthResponse {
        status: "ok",
        version: env!("CARGO_PKG_VERSION"),
        backend: "rust",
        ws_subscribers: bus.subscriber_count(),
    }))
}

#[derive(Serialize)]
pub struct VersionResponse {
    pub version: &'static str,
    pub build_profile: &'static str,
    pub commit: Option<&'static str>,
}

pub async fn version() -> AppResult<Json<VersionResponse>> {
    Ok(Json(VersionResponse {
        version: env!("CARGO_PKG_VERSION"),
        build_profile: if cfg!(debug_assertions) { "debug" } else { "release" },
        commit: option_env!("KALI_GIT_COMMIT"),
    }))
}

pub async fn get_config() -> AppResult<Json<config::AppConfig>> {
    let cfg = config::load()?;
    Ok(Json(cfg))
}

/// PATCH /config — proxied to Python so the YAML write stays in one place.
/// Preserves Python's status code so validation errors (422) and null-guard
/// rejections (422) surface cleanly to the UI instead of being flattened to
/// a generic 500.
pub async fn patch_config(ExtractJson(body): ExtractJson<serde_json::Value>) -> Response {
    match proxy::proxy_patch_json("/config", &body).await {
        Ok(payload) => (StatusCode::OK, Json(payload)).into_response(),
        Err(proxy::ProxyError::Upstream { status, body }) => {
            let code = StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_GATEWAY);
            (code, Json(body)).into_response()
        }
        Err(err) => (
            StatusCode::BAD_GATEWAY,
            Json(json!({
                "error": {
                    "code": "upstream_unavailable",
                    "message": err.to_string(),
                }
            })),
        )
            .into_response(),
    }
}

pub async fn voice_status() -> AppResult<Json<serde_json::Value>> {
    let body = proxy::proxy_get_json("/voice/status").await?;
    Ok(Json(body))
}

/// Build the router with a caller-supplied event bus. Phase 2 introduces
/// `/ws`, which needs a handle to the bus for fan-out; it is mounted as
/// stateful so the WS handler can `State<Arc<EventBus>>`.
pub fn router_with_bus(bus: Arc<EventBus>) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config).patch(patch_config))
        .route("/voice/status", get(voice_status))
        .route("/ws", get(ws::handler))
        .route(
            "/_internal/events",
            axum::routing::post(ingestion::ingest),
        )
        .with_state(bus)
}

/// Legacy constructor kept for tests that pre-date the event bus. Creates a
/// fresh, unconnected bus per call — fine for contract tests that do not
/// exercise `/ws`.
pub fn router() -> Router {
    router_with_bus(Arc::new(EventBus::new()))
}
