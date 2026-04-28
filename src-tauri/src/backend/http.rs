use std::sync::Arc;

use axum::{
    extract::{Extension, Json as ExtractJson, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Serialize;
use serde_json::json;

use crate::backend::config;
use crate::backend::error::AppResult;
use crate::backend::event_bus::EventBus;
use crate::backend::ingestion;
use crate::backend::proxy;
use crate::backend::voice::pipeline::Pipeline;
use crate::backend::ws;

/// Optional handle to the Rust-native voice pipeline. When present,
/// `/voice/start`, `/voice/stop`, `/voice/status` serve natively; when
/// `None` (the `engine: python` path), they proxy to Python.
pub type PipelineHandle = Option<Arc<Pipeline>>;

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

/// `engine: rust` → answer from the live Pipeline. `engine: python` (no
/// Extension) → proxy to Python. Response shape mirrors Python so the
/// UI's existing voice-status hook keeps working without changes.
pub async fn voice_status(Extension(pipeline): Extension<PipelineHandle>) -> Response {
    if let Some(pipeline) = pipeline {
        let state = pipeline.current_state();
        let body = json!({
            "available": true,
            "ready": true,
            "started": state.as_str() != "off",
            "state": state.as_str(),
            "mode": "wake_word",
            "models_ready": true,
            "missing_models": [],
        });
        return (StatusCode::OK, Json(body)).into_response();
    }
    match proxy::proxy_get_json("/voice/status").await {
        Ok(payload) => (StatusCode::OK, Json(payload)).into_response(),
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

pub async fn voice_start(Extension(pipeline): Extension<PipelineHandle>) -> Response {
    if let Some(pipeline) = pipeline {
        return match pipeline.start().await {
            Ok(()) => (
                StatusCode::OK,
                Json(json!({
                    "started": true,
                    "state": pipeline.current_state().as_str(),
                    "mode": "wake_word",
                })),
            )
                .into_response(),
            Err(e) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({
                    "error": {
                        "code": "pipeline_start_failed",
                        "message": e.to_string(),
                    }
                })),
            )
                .into_response(),
        };
    }
    proxy_voice("/voice/start").await
}

pub async fn voice_stop(Extension(pipeline): Extension<PipelineHandle>) -> Response {
    if let Some(pipeline) = pipeline {
        return match pipeline.stop().await {
            Ok(()) => (
                StatusCode::OK,
                Json(json!({
                    "stopped": true,
                    "state": pipeline.current_state().as_str(),
                })),
            )
                .into_response(),
            Err(e) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({
                    "error": {
                        "code": "pipeline_stop_failed",
                        "message": e.to_string(),
                    }
                })),
            )
                .into_response(),
        };
    }
    proxy_voice("/voice/stop").await
}

/// Common POST proxy for `/voice/start` and `/voice/stop`. Forwards an
/// empty JSON body — the Python endpoints don't require parameters,
/// and keeping the wire shape identical means the UI doesn't have to
/// know which engine is active.
async fn proxy_voice(path: &str) -> Response {
    match proxy::proxy_post_json(path, &json!({})).await {
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

/// Build the router with caller-supplied bus and pipeline handle. The
/// pipeline is `None` on the `engine: python` path; when present, the
/// `/voice/*` routes serve natively. Bus is passed via `State`,
/// pipeline via `Extension` — keeps the existing `State<Arc<EventBus>>`
/// extractor on `/health`, `/ws` etc. unchanged.
pub fn router_with_bus_and_pipeline(bus: Arc<EventBus>, pipeline: PipelineHandle) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config).patch(patch_config))
        .route("/voice/status", get(voice_status))
        .route("/voice/start", post(voice_start))
        .route("/voice/stop", post(voice_stop))
        .route("/ws", get(ws::handler))
        .route(
            "/_internal/events",
            axum::routing::post(ingestion::ingest),
        )
        .layer(Extension(pipeline))
        .with_state(bus)
}

/// Backwards-compatible constructor for tests that pre-date the
/// pipeline extension. Equivalent to passing `None` for the pipeline,
/// i.e. all `/voice/*` traffic proxies to Python.
pub fn router_with_bus(bus: Arc<EventBus>) -> Router {
    router_with_bus_and_pipeline(bus, None)
}

/// Legacy constructor kept for tests that pre-date the event bus.
/// Creates a fresh, unconnected bus per call — fine for contract tests
/// that do not exercise `/ws`. No native pipeline.
pub fn router() -> Router {
    router_with_bus(Arc::new(EventBus::new()))
}
