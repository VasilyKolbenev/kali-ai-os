pub mod config;
pub mod error;
pub mod http;

use std::net::SocketAddr;

use anyhow::Context;
use tokio::net::TcpListener;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing::info;

/// Bind address for the Phase 0 Rust backend. Python backend remains on 3005.
pub const RUST_BIND_ADDR: &str = "127.0.0.1:3006";

pub async fn serve() -> anyhow::Result<()> {
    let app = http::router()
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http());

    let addr: SocketAddr = RUST_BIND_ADDR.parse().context("parse bind address")?;
    let listener = TcpListener::bind(addr)
        .await
        .with_context(|| format!("bind {}", addr))?;
    info!("Rust backend listening on http://{}", addr);
    axum::serve(listener, app)
        .await
        .context("axum server terminated unexpectedly")?;
    Ok(())
}
