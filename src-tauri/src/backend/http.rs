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
use crate::backend::skills::catalog::CatalogClient;
use crate::backend::skills::registry::SkillsRegistry;
use crate::backend::voice::pipeline::Pipeline;
use crate::backend::ws;

/// Optional handle to the Rust-native voice pipeline. When present,
/// `/voice/start`, `/voice/stop`, `/voice/status` serve natively; when
/// `None` (the `engine: python` path), they proxy to Python.
pub type PipelineHandle = Option<Arc<Pipeline>>;

/// Optional handle to the local skills registry. When present,
/// `/skills/installed` serves natively from the in-memory index;
/// when `None`, the route proxies to Python.
pub type SkillsRegistryHandle = Option<Arc<SkillsRegistry>>;

/// Optional handle to the remote skills catalog client. When present,
/// `/skills/catalog/*` serves natively (HTTP fetch + on-disk cache);
/// when `None`, those routes proxy to Python.
pub type CatalogClientHandle = Option<Arc<CatalogClient>>;

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

/// `POST /skills/validate` — body `{"name": "<skill>"}`. Native iff
/// the registry is `Some` and finds the skill; else proxy to Python.
/// Response shape: `{status, skill_name, valid, errors, warnings}`.
pub async fn skills_validate(
    Extension(registry): Extension<SkillsRegistryHandle>,
    ExtractJson(body): ExtractJson<serde_json::Value>,
) -> Response {
    let name = body
        .get("name")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("");
    if name.is_empty() {
        return (
            StatusCode::OK,
            Json(json!({ "status": "error", "message": "name is required" })),
        )
            .into_response();
    }
    if let Some(reg) = registry {
        let manifest = match reg.get(name) {
            Some(m) => m,
            None => {
                return (
                    StatusCode::OK,
                    Json(json!({
                        "status": "error",
                        "message": format!("Skill '{name}' not found locally"),
                    })),
                )
                    .into_response();
            }
        };
        let result = crate::backend::skills::validator::validate_skill(&manifest.skill_dir);
        return (
            StatusCode::OK,
            Json(json!({
                "status": if result.errors.is_empty() { "ok" } else { "invalid" },
                "skill_name": name,
                "valid": result.valid,
                "errors": result.errors,
                "warnings": result.warnings,
            })),
        )
            .into_response();
    }
    proxy_post_with_body("/skills/validate", &json!({ "name": name })).await
}

/// `engine: rust` → answer from the in-memory skills registry.
/// `engine: python` (no Extension) → proxy to Python's `/skills/installed`.
/// Response shape mirrors Python — `{"results": [...], "count": N}`.
pub async fn skills_installed(
    Extension(registry): Extension<SkillsRegistryHandle>,
) -> Response {
    if let Some(reg) = registry {
        let manifests = reg.list_all();
        let count = manifests.len();
        let results: Vec<serde_json::Value> = manifests.iter().map(|m| m.to_json()).collect();
        return (
            StatusCode::OK,
            Json(json!({ "results": results, "count": count })),
        )
            .into_response();
    }
    match proxy::proxy_get_json("/skills/installed").await {
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

// ── /skills/install + /skills/uninstall (always proxy) ────────────
//
// Phase 4 Chunk 3 deliberately keeps the Python install path
// authoritative. The Python flow runs `kernel.builder.safety_gate`
// AST analysis on every Python script in a skill before deploy —
// re-implementing that safety check in Rust would either need pyo3
// (heavy embedding) or RustPython (incomplete) or a subprocess
// delegation that adds a moving part for marginal benefit.
//
// `kernel/skills/installer.py` (284 LoC) is battle-tested; install
// is a rare, cold operation (once per user per skill) so native
// Rust would give zero perceptible UX win. Phase 8 retires the
// proxy when the orchestration layer fully cuts over.
//
// Routing invariant preserved: UI hits Rust on `:3006` for every
// `/skills/*` endpoint; Rust forwards `install`/`uninstall` to
// Python on `:3005` while serving `installed` and `catalog/*`
// natively from Phase 4 Chunks 1-2.

pub async fn skills_install(ExtractJson(body): ExtractJson<serde_json::Value>) -> Response {
    proxy_post_with_body("/skills/install", &body).await
}

pub async fn skills_uninstall(ExtractJson(body): ExtractJson<serde_json::Value>) -> Response {
    proxy_post_with_body("/skills/uninstall", &body).await
}

/// Proxy a POST with the caller-supplied JSON body to Python,
/// preserving upstream status semantics so 404s and validation
/// failures surface cleanly to the UI.
async fn proxy_post_with_body(path: &str, body: &serde_json::Value) -> Response {
    match proxy::proxy_post_json(path, body).await {
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

// ── /skills/catalog/* ─────────────────────────────────────────────

#[derive(serde::Deserialize)]
pub struct CatalogQuery {
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub q: Option<String>,
}

#[derive(serde::Deserialize, Default)]
pub struct RefreshBody {
    #[serde(default)]
    pub force: bool,
}

pub async fn skills_catalog_sources(
    Extension(catalog): Extension<CatalogClientHandle>,
) -> Response {
    if let Some(client) = catalog {
        return (StatusCode::OK, Json(client.sources_summary())).into_response();
    }
    proxy_get("/skills/catalog/sources").await
}

pub async fn skills_catalog_list(
    Extension(catalog): Extension<CatalogClientHandle>,
    axum::extract::Query(query): axum::extract::Query<CatalogQuery>,
) -> Response {
    if let Some(client) = catalog {
        let entries = match (query.source.as_deref(), query.q.as_deref()) {
            (Some(src), Some(q)) if !q.trim().is_empty() => client
                .list_by_source(src)
                .await
                .into_iter()
                .filter(|e| {
                    let qlow = q.to_lowercase();
                    e.name.to_lowercase().contains(&qlow)
                        || e.description.to_lowercase().contains(&qlow)
                })
                .collect(),
            (Some(src), _) => client.list_by_source(src).await,
            (None, Some(q)) if !q.trim().is_empty() => client.search(q).await,
            _ => client.list_all().await,
        };
        let count = entries.len();
        let results: Vec<serde_json::Value> = entries.iter().map(|e| e.to_json()).collect();
        return (
            StatusCode::OK,
            Json(json!({ "results": results, "count": count })),
        )
            .into_response();
    }
    // Build query string for the proxy fallback.
    let mut qs = Vec::new();
    if let Some(s) = query.source {
        qs.push(format!("source={}", urlencoding_encode(&s)));
    }
    if let Some(q) = query.q {
        qs.push(format!("q={}", urlencoding_encode(&q)));
    }
    let suffix = if qs.is_empty() {
        String::new()
    } else {
        format!("?{}", qs.join("&"))
    };
    proxy_get(&format!("/skills/catalog{suffix}")).await
}

pub async fn skills_catalog_refresh(
    Extension(catalog): Extension<CatalogClientHandle>,
    body: Option<ExtractJson<RefreshBody>>,
) -> Response {
    let force = body.map(|ExtractJson(b)| b.force).unwrap_or(true);
    if let Some(client) = catalog {
        let total = client.refresh_all(force).await;
        return (
            StatusCode::OK,
            Json(json!({ "status": "ok", "total_entries": total })),
        )
            .into_response();
    }
    let body_json = json!({ "force": force });
    match proxy::proxy_post_json("/skills/catalog/refresh", &body_json).await {
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

/// Minimal URL-encoder for query-string pass-through. Only handles
/// the characters that the catalog query strings actually use
/// (spaces, `&`, `=`); good enough for one-hop proxying without
/// pulling in a full url-encoding crate.
fn urlencoding_encode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            ' ' => out.push_str("%20"),
            '&' => out.push_str("%26"),
            '=' => out.push_str("%3D"),
            '#' => out.push_str("%23"),
            '?' => out.push_str("%3F"),
            _ => out.push(ch),
        }
    }
    out
}

/// Generic GET proxy with the same status-passing semantics as the
/// existing `voice_status` proxy fallback. Used by every Phase 4
/// route that wants to forward to Python when the native handle is
/// `None`.
async fn proxy_get(path: &str) -> Response {
    match proxy::proxy_get_json(path).await {
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

/// Full constructor — every backend handle in one call. Tests + serve()
/// converge on this; the older constructors below are thin wrappers
/// that pass `None` for the handles they don't care about.
pub fn router_full(
    bus: Arc<EventBus>,
    pipeline: PipelineHandle,
    skills: SkillsRegistryHandle,
    catalog: CatalogClientHandle,
) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
        .route("/config", get(get_config).patch(patch_config))
        .route("/voice/status", get(voice_status))
        .route("/voice/start", post(voice_start))
        .route("/voice/stop", post(voice_stop))
        .route("/skills/installed", get(skills_installed))
        .route("/skills/install", post(skills_install))
        .route("/skills/uninstall", post(skills_uninstall))
        .route("/skills/validate", post(skills_validate))
        .route("/skills/catalog/sources", get(skills_catalog_sources))
        .route("/skills/catalog", get(skills_catalog_list))
        .route("/skills/catalog/refresh", post(skills_catalog_refresh))
        .route("/ws", get(ws::handler))
        .route(
            "/_internal/events",
            axum::routing::post(ingestion::ingest),
        )
        .layer(Extension(pipeline))
        .layer(Extension(skills))
        .layer(Extension(catalog))
        .with_state(bus)
}

/// Backwards-compatible constructor — bus + pipeline only, skills +
/// catalog default to `None` (those routes proxy to Python).
pub fn router_with_bus_and_pipeline(bus: Arc<EventBus>, pipeline: PipelineHandle) -> Router {
    router_full(bus, pipeline, None, None)
}

/// Backwards-compatible constructor for tests that pre-date the
/// pipeline extension. Equivalent to passing `None` for the pipeline,
/// i.e. all `/voice/*` and `/skills/*` native routes proxy to Python.
pub fn router_with_bus(bus: Arc<EventBus>) -> Router {
    router_full(bus, None, None, None)
}

/// Legacy constructor kept for tests that pre-date the event bus.
/// Creates a fresh, unconnected bus per call — fine for contract tests
/// that do not exercise `/ws`. No native pipeline, no native skills.
pub fn router() -> Router {
    router_with_bus(Arc::new(EventBus::new()))
}
