//! Headless Rust backend runner for development and smoke testing.
//!
//! Runs `kali_desktop::backend::serve()` standalone — same axum router that
//! Tauri's main process boots, but without the WebView. Useful for:
//!   - end-to-end smoke against a running Python kernel without spinning up
//!     the full Tauri graphics stack
//!   - future CI smoke that exercises the real wire path
//!   - manual `curl` / `websocat` verification while iterating on Rust code
//!
//! Run with: `cargo run --bin backend_dev`. Binds to 127.0.0.1:3006 and
//! talks to a Python backend on 127.0.0.1:3005 (override with
//! `KALI_PYTHON_BACKEND_URL`). Stop with Ctrl+C.

use kali_desktop::backend;

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "kali_desktop=info,tower_http=info".into()),
        )
        .init();

    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    rt.block_on(backend::serve())
}
