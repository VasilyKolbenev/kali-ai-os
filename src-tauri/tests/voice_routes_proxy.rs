//! Phase 3 Chunk 8 — proxy-mode contract test for `/voice/*` routes.
//!
//! Default Rust router (no Pipeline Extension) must forward all three
//! voice routes to Python. This is the `voice.engine: python` path —
//! i.e. existing pre-Chunk-7 behaviour preserved, just rehosted under
//! the Rust port. The `engine: rust` native path bypasses Python and
//! lives in `pipeline.rs`; it's covered by Vasily's manual rehearsal
//! at the close of Phase 3, not here.
//!
//! Single combined test by design: `KALI_PYTHON_BACKEND_URL` is a
//! process-wide env var. Splitting into per-route tests would race
//! when cargo runs them in parallel (each `start_rust_against` sets
//! the same var to its own mock port). One mock + one Rust + three
//! sequential calls keeps the contract assertion clean.

use axum::{
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use std::net::SocketAddr;
use tokio::net::TcpListener;

async fn start_mock_python() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new()
        .route(
            "/voice/start",
            post(|| async {
                Json(json!({
                    "started": true,
                    "state": "listening",
                    "mode": "wake_word"
                }))
            }),
        )
        .route(
            "/voice/stop",
            post(|| async {
                Json(json!({
                    "stopped": true,
                    "state": "idle"
                }))
            }),
        )
        .route(
            "/voice/status",
            get(|| async {
                Json(json!({
                    "available": true,
                    "ready": true,
                    "started": false,
                    "state": "idle",
                    "mode": "wake_word",
                    "models_ready": true,
                    "missing_models": []
                }))
            }),
        );
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

async fn start_rust_against(python_addr: SocketAddr) -> SocketAddr {
    std::env::set_var(
        "KALI_PYTHON_BACKEND_URL",
        format!("http://{}", python_addr),
    );
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn voice_routes_proxy_through_rust_when_no_native_pipeline() {
    let py = start_mock_python().await;
    let rust = start_rust_against(py).await;
    let client = reqwest::Client::new();

    // POST /voice/start — proxy
    let resp = client
        .post(format!("http://{}/voice/start", rust))
        .json(&json!({}))
        .send()
        .await
        .expect("POST /voice/start");
    assert_eq!(resp.status(), 200, "voice/start proxy must return 200");
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["started"], true);
    assert_eq!(body["state"], "listening");
    assert_eq!(body["mode"], "wake_word");

    // POST /voice/stop — proxy
    let resp = client
        .post(format!("http://{}/voice/stop", rust))
        .json(&json!({}))
        .send()
        .await
        .expect("POST /voice/stop");
    assert_eq!(resp.status(), 200, "voice/stop proxy must return 200");
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["stopped"], true);
    assert_eq!(body["state"], "idle");

    // GET /voice/status — proxy with full payload preserved
    let resp = reqwest::get(format!("http://{}/voice/status", rust))
        .await
        .expect("GET /voice/status");
    assert_eq!(resp.status(), 200, "voice/status proxy must return 200");
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["available"], true);
    assert_eq!(body["ready"], true);
    assert_eq!(body["started"], false);
    assert_eq!(body["state"], "idle");
    assert_eq!(body["mode"], "wake_word");
    assert_eq!(body["models_ready"], true);
    assert!(body["missing_models"].is_array());
}
