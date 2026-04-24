use axum::{routing::get, Json, Router};
use serde::Serialize;

use crate::backend::error::AppResult;

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

pub fn router() -> Router {
    Router::new().route("/health", get(health))
}
