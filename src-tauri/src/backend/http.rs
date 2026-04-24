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
use crate::backend::proxy;

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub version: &'static str,
    pub backend: &'static str,
}

pub async fn health() -> AppResult<Json<HealthResponse>> {
    Ok(Json(HealthResponse {
        status: "ok",
        version: env!("CARGO_PKG_VERSION"),
        backend: "rust",
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

pub fn router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config).patch(patch_config))
        .route("/voice/status", get(voice_status))
}
