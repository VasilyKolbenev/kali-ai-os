//! Integration test for /version. Spawns a minimal axum instance on an
//! ephemeral port and hits it via reqwest — no Tauri, no Python required.

use axum::Router;
use serde_json::Value;
use std::net::SocketAddr;
use tokio::net::TcpListener;

async fn start_test_server() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn version_returns_semantic_shape() {
    let addr = start_test_server().await;
    let url = format!("http://{}/version", addr);

    let resp = reqwest::get(&url).await.expect("GET /version");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON parse");

    assert!(body["version"].is_string());
    assert!(body["build_profile"].is_string());
    assert!(body["commit"].is_string() || body["commit"].is_null());
}
