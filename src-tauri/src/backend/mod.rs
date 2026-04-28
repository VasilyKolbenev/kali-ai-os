pub mod config;
pub mod error;
pub mod event_bus;
pub mod http;
pub mod ingestion;
pub mod models;
pub mod proxy;
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

    let app = http::router_with_bus_and_pipeline(bus, pipeline)
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
