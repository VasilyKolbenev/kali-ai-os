pub mod config;
pub mod error;
pub mod event_bus;
pub mod http;
pub mod ingestion;
pub mod models;
pub mod proxy;
pub mod ws;

use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Context;
use tokio::net::TcpListener;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing::info;

/// Bind address for the Phase 0 Rust backend. Python backend remains on 3005.
pub const RUST_BIND_ADDR: &str = "127.0.0.1:3006";

pub async fn serve() -> anyhow::Result<()> {
    let bus = Arc::new(event_bus::EventBus::new());
    let app = http::router_with_bus(bus)
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
