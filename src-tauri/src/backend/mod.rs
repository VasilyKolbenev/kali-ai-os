pub mod auth;
pub mod config;
pub mod crash;
pub mod error;
pub mod event_bus;
pub mod http;
pub mod ingestion;
pub mod model_registry;
pub mod models;
pub mod proxy;
pub mod skills;
pub mod updater;
pub mod voice;
pub mod ws;

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use axum::http::{header, HeaderValue, Method};
use tokio::net::TcpListener;
use tower_http::cors::{AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing::{info, warn};

use crate::backend::skills::catalog::{CatalogClient, CatalogClientOpts};
use crate::backend::skills::registry::{default_sources, SkillsRegistry};
use crate::backend::voice::pipeline::{Pipeline, PipelineDeps};

/// Default bind for the Rust backend — loopback only, matching the Python
/// backend's `KALI_HOST` default (`127.0.0.1`). The Tauri webview talks over
/// localhost, so this is friction-free out of the box and exposes nothing to
/// the LAN. Python backend remains on 3005.
pub const DEFAULT_RUST_BIND_ADDR: &str = "127.0.0.1:3006";

/// LAN bind — used only when the user explicitly opts in (`KALI_LAN=1`), so a
/// phone on the same network can reach the backend. LAN access is gated by
/// the per-install token (see [`auth`]); loopback stays exempt.
pub const LAN_RUST_BIND_ADDR: &str = "0.0.0.0:3006";

/// Resolve the bind address (safe-by-default).
///
/// Precedence:
/// 1. `KALI_RUST_BIND` — full `host:port` override (advanced / tests).
/// 2. `KALI_LAN=1` (or `true`) — bind `0.0.0.0:3006` for LAN access.
/// 3. Default — `127.0.0.1:3006` (loopback only).
fn resolve_bind_addr() -> String {
    if let Ok(explicit) = std::env::var("KALI_RUST_BIND") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }
    let lan = std::env::var("KALI_LAN")
        .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(false);
    if lan {
        LAN_RUST_BIND_ADDR.to_string()
    } else {
        DEFAULT_RUST_BIND_ADDR.to_string()
    }
}

/// Standalone-старт axum (:3006) — для `backend_dev` bin; bind-сигнал не нужен.
pub async fn serve() -> anyhow::Result<()> {
    let (tx, _rx) = std::sync::mpsc::channel();
    serve_with_bind_signal(tx).await
}

/// Стартовать Rust axum (:3006), отправив authoritative bind-результат в
/// `bind_tx`. `AddrInUse` → `PortOccupied`; любая другая pre-bind/bind ошибка
/// возвращается как `Err` БЕЗ отправки — вызывающий трактует dropped-sender
/// (channel disconnect) как `RustStartupFailed`, не «порт занят».
pub(crate) async fn serve_with_bind_signal(
    bind_tx: std::sync::mpsc::Sender<crate::startup::BindOutcome>,
) -> anyhow::Result<()> {
    let bus = Arc::new(event_bus::EventBus::new());

    // Auto-update: удалить каталоги старых/непарсящихся загрузок при старте
    // (stateless-правило спеки; залоченное пропускается молча).
    crate::backend::updater::cleanup_updates_dir(
        &crate::backend::updater::updates_dir(),
        env!("CARGO_PKG_VERSION"),
    );

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

    // Per-install control-plane token: generated on first run, reused after.
    // Loopback (the Tauri webview) is exempt from auth; LAN callers must
    // present this token. Fail loudly if it can't be persisted — running the
    // LAN surface without a token would reopen the audit BLOCKER.
    let token = auth::load_or_create().context("load control-plane token")?;

    let app = auth::with_auth(http::router_full(bus, pipeline, skills, catalog), token)
        .layer(build_cors_layer())
        // Record only method + PATH in the request span — never the query string,
        // which carries the LAN control-plane token on /ws?token=… (a debug-level
        // full-URI span would leak it into logs).
        .layer(TraceLayer::new_for_http().make_span_with(
            |req: &axum::http::Request<axum::body::Body>| {
                tracing::info_span!(
                    "http",
                    method = %req.method(),
                    path = %req.uri().path(),
                )
            },
        ));

    let bind = resolve_bind_addr();
    let addr: SocketAddr = bind
        .parse()
        .with_context(|| format!("parse bind address {bind}"))?;
    let listener = match TcpListener::bind(addr).await {
        Ok(l) => {
            let _ = bind_tx.send(crate::startup::BindOutcome::Ok);
            l
        }
        Err(e) => {
            let outcome = if e.kind() == std::io::ErrorKind::AddrInUse {
                crate::startup::BindOutcome::PortOccupied
            } else {
                crate::startup::BindOutcome::StartupFailed
            };
            let _ = bind_tx.send(outcome);
            return Err(e).with_context(|| format!("bind {}", addr));
        }
    };
    if addr.ip().is_loopback() {
        info!("Rust backend listening on http://{} (loopback only)", addr);
    } else {
        warn!(
            "Rust backend listening on http://{} (LAN exposed — token auth enforced for non-loopback)",
            addr
        );
    }
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .context("axum server terminated unexpectedly")?;
    Ok(())
}

/// Allowed cross-origin sources — kept in lockstep with the Tauri
/// shell's `BACKEND_CORS_ORIGINS` (see `lib.rs`) so the Rust backend on
/// `:3006` honours the same origins as the Python backend on `:3005`.
const CORS_ALLOWED_ORIGINS: [&str; 7] = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:1421",
    "http://127.0.0.1:1421",
];

/// Build the CORS layer for the backend.
///
/// audit SEC-2: CORS locked to known origins. The companion LAN token-auth
/// (loopback-exempt) is now enforced by the `auth` middleware (see
/// [`auth::require_token`]) — non-loopback callers must present the
/// per-install token on every route except `/health` and `/version`.
///
/// The bind is loopback-only by default (`127.0.0.1:3006`); LAN exposure is
/// opt-in (`KALI_LAN=1`). Cross-origin reads are restricted to the Tauri
/// shell and the Vite dev server instead of `permissive()`, which let any
/// website call `/chat` and `/dashboard`.
fn build_cors_layer() -> CorsLayer {
    let origins: Vec<HeaderValue> = CORS_ALLOWED_ORIGINS
        .iter()
        .filter_map(|origin| HeaderValue::from_str(origin).ok())
        .collect();
    CorsLayer::new()
        .allow_origin(AllowOrigin::list(origins))
        .allow_methods([Method::GET, Method::POST, Method::PATCH])
        // Only CONTENT_TYPE is listed here. X-KALI-Token and Authorization are intentionally
        // omitted: the only token-presenting client is the Dio mobile HTTP stack, which is
        // not browser-CORS-constrained, and the desktop Tauri webview talks over loopback
        // (exempt from the auth gate entirely).  A future browser-based LAN client would
        // need those headers added here.
        .allow_headers([header::CONTENT_TYPE])
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
            warn!(
                ?err,
                "skills registry: failed to resolve sources, proxy fallback"
            );
            return None;
        }
    };
    let registry = SkillsRegistry::new(sources);
    if let Err(err) = registry.discover() {
        warn!(
            ?err,
            "skills registry: initial discovery failed, proxy fallback"
        );
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
            warn!(
                ?err,
                "catalog client: initialisation failed, proxy fallback"
            );
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
            warn!(
                ?err,
                "could not load config — voice engine defaults to python (proxy)"
            );
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
