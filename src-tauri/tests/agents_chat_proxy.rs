//! Proxy contract for the `/dashboard`, `/agents/*`, and `/chat` routes.
//!
//! These endpoints still live in Python (`kernel.*`); the Rust
//! orchestration migration has not reached them yet. The Rust dispatcher
//! owns the routes (clients hit `:3006` consistently) and forwards
//! verbatim to Python on `:3005`, preserving the wire shape (no body for
//! GET, path param for `/agents/{name}/load|unload`, JSON body for
//! `/chat`). Phase 8 retires these proxies as the routes go native.
//!
//! Single combined `#[tokio::test]` because `KALI_PYTHON_BACKEND_URL`
//! is process-wide — splitting per route would race in parallel.
//! Cross-binary parallelism is fine (each integration-test file is a
//! separate process), so this test does not collide with the env var
//! set inside the other proxy-contract tests.

use axum::{
    extract::Path,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use tokio::net::TcpListener;

#[tokio::test]
async fn dashboard_agents_chat_proxy_to_python() {
    // ── Mock Python — the six proxied routes, each counting hits ──
    let dash_hits = Arc::new(AtomicUsize::new(0));
    let agents_hits = Arc::new(AtomicUsize::new(0));
    let running_hits = Arc::new(AtomicUsize::new(0));
    let load_hits = Arc::new(AtomicUsize::new(0));
    let unload_hits = Arc::new(AtomicUsize::new(0));
    let chat_hits = Arc::new(AtomicUsize::new(0));

    let d_state = dash_hits.clone();
    let a_state = agents_hits.clone();
    let r_state = running_hits.clone();
    let l_state = load_hits.clone();
    let u_state = unload_hits.clone();
    let c_state = chat_hits.clone();

    let app = Router::new()
        .route(
            "/dashboard",
            get(move || {
                let counter = d_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({ "marker": "dash" }))
                }
            }),
        )
        .route(
            "/agents",
            get(move || {
                let counter = a_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    // Real Python returns a JSON array of agents.
                    Json(json!([{ "name": "demo-agent" }]))
                }
            }),
        )
        .route(
            "/agents/running",
            get(move || {
                let counter = r_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!([{ "name": "demo-agent" }]))
                }
            }),
        )
        .route(
            "/agents/:name/load",
            post(move |Path(name): Path<String>| {
                let counter = l_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({ "status": "loaded", "name": name }))
                }
            }),
        )
        .route(
            "/agents/:name/unload",
            post(move |Path(name): Path<String>| {
                let counter = u_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({ "status": "unloaded", "name": name }))
                }
            }),
        )
        .route(
            "/chat",
            post(move |Json(body): Json<Value>| {
                let counter = c_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    let text = body["text"].as_str().unwrap_or("").to_string();
                    Json(json!({ "response": format!("echo: {text}") }))
                }
            }),
        );

    let py_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let py_addr: SocketAddr = py_listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(py_listener, app).await.unwrap();
    });

    // ── Rust dispatcher against the mock ──
    std::env::set_var("KALI_PYTHON_BACKEND_URL", format!("http://{}", py_addr));
    let rust_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let rust_addr: SocketAddr = rust_listener.local_addr().unwrap();
    let rust_app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(rust_listener, rust_app).await.unwrap();
    });

    let client = reqwest::Client::new();

    // 1. GET /dashboard forwards without a body.
    let resp = client
        .get(format!("http://{}/dashboard", rust_addr))
        .send()
        .await
        .expect("GET /dashboard");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["marker"], "dash");
    assert_eq!(dash_hits.load(Ordering::Relaxed), 1);

    // 2. GET /agents forwards and preserves the array shape.
    let resp = client
        .get(format!("http://{}/agents", rust_addr))
        .send()
        .await
        .expect("GET /agents");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body[0]["name"], "demo-agent");
    assert_eq!(agents_hits.load(Ordering::Relaxed), 1);

    // 3. GET /agents/running forwards without a body.
    let resp = client
        .get(format!("http://{}/agents/running", rust_addr))
        .send()
        .await
        .expect("GET /agents/running");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert!(body.is_array());
    assert_eq!(running_hits.load(Ordering::Relaxed), 1);

    // 4. POST /agents/{name}/load forwards the path param.
    let resp = client
        .post(format!("http://{}/agents/demo-agent/load", rust_addr))
        .send()
        .await
        .expect("POST /agents/demo-agent/load");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["status"], "loaded");
    assert_eq!(body["name"], "demo-agent");
    assert_eq!(load_hits.load(Ordering::Relaxed), 1);

    // 5. POST /agents/{name}/unload forwards the path param.
    let resp = client
        .post(format!("http://{}/agents/demo-agent/unload", rust_addr))
        .send()
        .await
        .expect("POST /agents/demo-agent/unload");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["status"], "unloaded");
    assert_eq!(unload_hits.load(Ordering::Relaxed), 1);

    // 6. POST /chat forwards the JSON body.
    let resp = client
        .post(format!("http://{}/chat", rust_addr))
        .json(&json!({ "text": "hi" }))
        .send()
        .await
        .expect("POST /chat");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["response"], "echo: hi");
    assert_eq!(chat_hits.load(Ordering::Relaxed), 1);
}
