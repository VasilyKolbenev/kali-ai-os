use axum::{routing::get, Json, Router};
use serde::Serialize;

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

pub async fn voice_status() -> AppResult<Json<serde_json::Value>> {
    let body = proxy::proxy_get_json("/voice/status").await?;
    Ok(Json(body))
}

pub fn router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config))
        .route("/voice/status", get(voice_status))
}
