//! Proxy test: start a mock Python on an ephemeral port, point the Rust
//! proxy at it, verify Rust forwards request and response faithfully.

use axum::{routing::get, Json, Router};
use serde_json::{json, Value};
use std::net::SocketAddr;
use tokio::net::TcpListener;

async fn start_mock_python() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
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

async fn start_rust_with_python(python_addr: SocketAddr) -> SocketAddr {
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
async fn voice_status_proxies_to_python() {
    let py_addr = start_mock_python().await;
    let rust_addr = start_rust_with_python(py_addr).await;

    let resp = reqwest::get(format!("http://{}/voice/status", rust_addr))
        .await
        .expect("GET /voice/status");
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await.expect("JSON parse");
    assert_eq!(body["mode"], "wake_word");
    assert_eq!(body["state"], "idle");
    assert_eq!(body["available"], true);
}
