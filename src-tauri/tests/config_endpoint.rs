//! Integration test for GET /config.
//!
//! Sets KALI_CONFIG to the real repo config file so the handler has
//! something to read.

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
async fn config_returns_yaml_as_json() {
    std::env::set_var("KALI_CONFIG", "../config/kali.yaml");

    let addr = start_test_server().await;
    let url = format!("http://{}/config", addr);

    let resp = reqwest::get(&url).await.expect("GET /config");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON parse");

    for key in ["server", "voice", "llm", "schedule"] {
        assert!(body.get(key).is_some(), "missing top-level key '{}'", key);
    }
    assert!(body["voice"]["mode"].is_string());
    assert!(body["voice"]["auto_start"].is_boolean());
    assert!(body["server"]["port"].is_number());
    assert!(body["schedule"]["timezone"].is_string());
}
