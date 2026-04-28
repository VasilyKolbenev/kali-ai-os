pub mod config;
pub mod error;
pub mod event_bus;
pub mod http;
pub mod ingestion;
pub mod models;
pub mod proxy;
pub mod skills;
pub mod voice;
pub mod ws;

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use tokio::net::TcpListener;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing::{info, warn};

use crate::backend::skills::catalog::{CatalogClient, CatalogClientOpts};
use crate::backend::skills::registry::{default_sources, SkillsRegistry};
use crate::backend::voice::pipeline::{Pipeline, PipelineDeps};

/// Bind address for the Phase 0 Rust backend. Python backend remains on 3005.
pub const RUST_BIND_ADDR: &str = "127.0.0.1:3006";

pub async fn serve() -> anyhow::Result<()> {
    let bus = Arc::new(event_bus::EventBus::new());

    // Engine selector: read config to decide whether to spin up the
    // Rust-native voice pipeline. Failure to load config falls back to
    // `engine=python` with a warning — keeps the backend bootable in
    // dev shells where kali.yaml is missing.
    let pipeline = match build_pipeline_if_enabled(&bus).await {
        Ok(p) => p,
        Err(err) => {
            // Fail loudly per Vasily's call: a configured engine=rust
            // that can't initialise should NOT silently fall back to
            // python — that masks broken installs (missing venv, no
            // VAD model). Surface and abort.
            return Err(err);
        }
    };

    let skills = build_skills_registry();
    let catalog = build_catalog_client();
    let app = http::router_full(bus, pipeline, skills, catalog)
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http());

    let addr: SocketAddr = RUST_BIND_ADDR.parse().context("parse bind address")?;
    let listener = TcpListener::bind(addr)
        .await
        .with_context(|| format!("bind {}", addr))?;
    info!("Rust backend listening on http://{}", addr);
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .context("axum server terminated unexpectedly")?;
    Ok(())
}

/// Construct the local skills registry from the default source list
/// (user + builtin). Failure is non-fatal: log and degrade to `None`
/// so `/skills/installed` falls back to the Python proxy. The local
/// registry is purely a performance + Phase 8 prerequisite — the
/// proxy path keeps working as a safety net.
fn build_skills_registry() -> http::SkillsRegistryHandle {
    let sources = match default_sources() {
        Ok(s) => s,
        Err(err) => {
            warn!(?err, "skills registry: failed to resolve sources, proxy fallback");
            return None;
        }
    };
    let registry = SkillsRegistry::new(sources);
    if let Err(err) = registry.discover() {
        warn!(?err, "skills registry: initial discovery failed, proxy fallback");
        return None;
    }
    Some(Arc::new(registry))
}

/// Construct the remote-catalog client. Failure to resolve the cache
/// directory degrades gracefully to `None` so `/skills/catalog/*`
/// routes proxy to Python. The local registry is the authoritative
/// source for installed skills; the catalog is read-only browsing.
fn build_catalog_client() -> http::CatalogClientHandle {
    let opts = match CatalogClientOpts::defaults() {
        Ok(o) => o,
        Err(err) => {
            warn!(?err, "catalog client: defaults unavailable, proxy fallback");
            return None;
        }
    };
    match CatalogClient::new(opts) {
        Ok(client) => Some(client),
        Err(err) => {
            warn!(?err, "catalog client: initialisation failed, proxy fallback");
            None
        }
    }
}

/// Construct the Rust-native voice pipeline iff `voice.engine == "rust"`.
/// Returns `Ok(None)` when the engine is `"python"` (default) or when
/// config loading itself fails (config-loading errors are not fatal —
/// the rest of the backend can still serve `/health` etc.).
async fn build_pipeline_if_enabled(
    bus: &Arc<event_bus::EventBus>,
) -> anyhow::Result<http::PipelineHandle> {
    let cfg = match config::load() {
        Ok(c) => c,
        Err(err) => {
            warn!(?err, "could not load config — voice engine defaults to python (proxy)");
            return Ok(None);
        }
    };
    if cfg.voice.engine.as_str() != "rust" {
        info!(engine = %cfg.voice.engine, "voice routes will proxy to Python");
        return Ok(None);
    }

    info!("voice.engine=rust — constructing native pipeline");
    let deps = PipelineDeps {
        voice_config: cfg.voice.clone(),
        vad_model_path: PathBuf::from(
            std::env::var("KALI_VAD_MODEL")
                .unwrap_or_else(|_| "../models/silero_vad.onnx".to_string()),
        ),
        python_exe: std::env::var("KALI_PY")
            .unwrap_or_else(|_| "../.venv/Scripts/python.exe".to_string()),
        bridge_cwd: std::env::var("KALI_BRIDGE_CWD").unwrap_or_else(|_| "..".to_string()),
        chat_url: std::env::var("KALI_CHAT_URL")
            .unwrap_or_else(|_| format!("{}/chat", proxy::python_backend_url())),
        event_bus: (**bus).clone(),
    };

    let pipeline = Pipeline::new(deps)
        .await
        .context("construct native voice pipeline")?;
    Ok(Some(Arc::new(pipeline)))
}
