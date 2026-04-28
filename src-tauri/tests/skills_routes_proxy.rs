//! Phase 4 Chunk 3 — proxy contract for `/skills/install` and
//! `/skills/uninstall`.
//!
//! Per the design call (Option C), these routes deliberately stay in
//! Python — `kernel.builder.safety_gate` AST analysis on user-supplied
//! Python scripts is the long pole, and porting it to Rust would need
//! pyo3 / RustPython / subprocess delegation. The Rust dispatcher
//! still owns the routes (UI hits `:3006` consistently) and forwards
//! the body verbatim to Python on `:3005`. Phase 8 cleanup will
//! replace the proxy with native logic once orchestration cuts over.
//!
//! Single combined `#[tokio::test]` because `KALI_PYTHON_BACKEND_URL`
//! is process-wide — splitting per route would race in parallel.

use axum::{
    routing::post,
    Json, Router,
};
use serde_json::{json, Value};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use tokio::net::TcpListener;

#[tokio::test]
async fn skills_install_and_uninstall_proxy_to_python() {
    // ── Mock Python ──
    let install_hits = Arc::new(AtomicUsize::new(0));
    let uninstall_hits = Arc::new(AtomicUsize::new(0));

    let install_state = install_hits.clone();
    let uninstall_state = uninstall_hits.clone();

    let app = Router::new()
        .route(
            "/skills/install",
            post(move |Json(body): Json<Value>| {
                let counter = install_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    // Echo back what we got + the install-shape Python emits.
                    Json(json!({
                        "status": "ok",
                        "skill_name": body["name"].as_str().unwrap_or("unknown"),
                        "install_path": format!("/fake/path/{}", body["name"].as_str().unwrap_or("?")),
                        "warnings": [],
                    }))
                }
            }),
        )
        .route(
            "/skills/uninstall",
            post(move |Json(body): Json<Value>| {
                let counter = uninstall_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({
                        "status": "ok",
                        "removed": true,
                        "name": body["name"].as_str().unwrap_or("unknown"),
                    }))
                }
            }),
        );

    let py_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let py_addr: SocketAddr = py_listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(py_listener, app).await.unwrap();
    });

    // ── Rust against the mock ──
    std::env::set_var("KALI_PYTHON_BACKEND_URL", format!("http://{}", py_addr));
    let rust_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let rust_addr: SocketAddr = rust_listener.local_addr().unwrap();
    let rust_app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(rust_listener, rust_app).await.unwrap();
    });

    let client = reqwest::Client::new();

    // ── 1. /skills/install forwards the body and the response ──
    let resp = client
        .post(format!("http://{}/skills/install", rust_addr))
        .json(&json!({ "source_id": "anthropic", "name": "weather" }))
        .send()
        .await
        .expect("POST /skills/install");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["status"], "ok");
    assert_eq!(body["skill_name"], "weather");
    assert_eq!(install_hits.load(Ordering::Relaxed), 1);

    // ── 2. /skills/uninstall forwards the body and the response ──
    let resp = client
        .post(format!("http://{}/skills/uninstall", rust_addr))
        .json(&json!({ "name": "weather" }))
        .send()
        .await
        .expect("POST /skills/uninstall");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["status"], "ok");
    assert_eq!(body["removed"], true);
    assert_eq!(body["name"], "weather");
    assert_eq!(uninstall_hits.load(Ordering::Relaxed), 1);
}
