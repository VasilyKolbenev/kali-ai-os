//! Integration tests for /config: GET reads YAML natively, PATCH proxies
//! to Python. Serialized via a file-scope mutex because each test mutates
//! process-wide env vars (`KALI_CONFIG`, `KALI_PYTHON_BACKEND_URL`) and
//! Rust's default test runner executes tests in one binary in parallel.

use axum::{
    extract::Json as ExtractJson,
    http::StatusCode,
    routing::patch,
    Json, Router,
};
use serde_json::{json, Value};
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use tokio::net::TcpListener;

static TEST_LOCK: Mutex<()> = Mutex::new(());

async fn start_rust_only() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app: Router = kali_desktop::backend::http::router();
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
    start_rust_only().await
}

#[tokio::test]
async fn config_returns_yaml_as_json() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    std::env::set_var("KALI_CONFIG", "../config/kali.yaml");

    let addr = start_rust_only().await;
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

#[tokio::test]
async fn patch_config_proxies_body_and_echoes_python_response() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let received_body = Arc::new(Mutex::new(json!(null)));
    let received_clone = received_body.clone();

    let python_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let python_addr = python_listener.local_addr().unwrap();
    let python_app = Router::new().route(
        "/config",
        patch(move |ExtractJson(body): ExtractJson<Value>| {
            let received = received_clone.clone();
            async move {
                *received.lock().unwrap() = body;
                Json(json!({
                    "voice": { "wake_word": "kali", "mode": "wake_word" },
                    "llm": { "cloud_provider": "openai" }
                }))
            }
        }),
    );
    tokio::spawn(async move {
        axum::serve(python_listener, python_app).await.unwrap();
    });

    let rust_addr = start_rust_with_python(python_addr).await;
    let resp = reqwest::Client::new()
        .patch(format!("http://{}/config", rust_addr))
        .json(&json!({ "voice": { "wake_word": "kali" } }))
        .send()
        .await
        .expect("PATCH /config");

    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.unwrap();
    assert_eq!(body["voice"]["wake_word"], "kali");
    assert_eq!(
        *received_body.lock().unwrap(),
        json!({ "voice": { "wake_word": "kali" } }),
    );
}

#[tokio::test]
async fn patch_config_preserves_422_from_python() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let python_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let python_addr = python_listener.local_addr().unwrap();
    let python_app = Router::new().route(
        "/config",
        patch(|ExtractJson(_): ExtractJson<Value>| async {
            (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({ "error": "invalid config", "detail": ["mode: bad enum"] })),
            )
        }),
    );
    tokio::spawn(async move {
        axum::serve(python_listener, python_app).await.unwrap();
    });

    let rust_addr = start_rust_with_python(python_addr).await;
    let resp = reqwest::Client::new()
        .patch(format!("http://{}/config", rust_addr))
        .json(&json!({ "voice": { "mode": "nope" } }))
        .send()
        .await
        .expect("PATCH /config");

    assert_eq!(resp.status(), 422);
    let body: Value = resp.json().await.unwrap();
    assert_eq!(body["error"], "invalid config");
}

#[tokio::test]
async fn patch_config_returns_502_when_python_down() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    // Point Rust at a definitely-unavailable port.
    std::env::set_var("KALI_PYTHON_BACKEND_URL", "http://127.0.0.1:1");
    let rust_addr = start_rust_only().await;

    let resp = reqwest::Client::new()
        .patch(format!("http://{}/config", rust_addr))
        .json(&json!({ "voice": { "wake_word": "kali" } }))
        .send()
        .await
        .expect("PATCH /config");

    assert_eq!(resp.status(), 502);
    let body: Value = resp.json().await.unwrap();
    assert_eq!(body["error"]["code"], "upstream_unavailable");
}
