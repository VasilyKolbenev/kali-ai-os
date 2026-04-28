//! Phase 4 Chunk 5 — proxy contract for the legacy `/catalog/*` routes.
//!
//! Per the design call (Option C, same as Chunk 3), the `.kali-agent`
//! package format stays in Python: `pack_agent`, `install_package`,
//! and `get_package_info` sit on top of the path-traversal-hardened
//! zip extractor in `kernel/skills/installer.py`. Porting those guards
//! to Rust would be high-risk for cold-path operations. The Rust
//! dispatcher still owns the routes (UI hits `:3006` consistently)
//! and forwards verbatim to Python on `:3005`, preserving the wire
//! shape (raw query string for GET, JSON body for POST, path param
//! for `/catalog/pack/{name}`).
//!
//! Single combined `#[tokio::test]` because `KALI_PYTHON_BACKEND_URL`
//! is process-wide — splitting per route would race in parallel.
//! Cross-binary parallelism is fine (each integration-test file is a
//! separate process), so this test does not collide with the env var
//! set inside `skills_routes_proxy`.

use axum::{
    extract::{Path, Query},
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use tokio::net::TcpListener;

#[tokio::test]
async fn catalog_routes_proxy_to_python() {
    // ── Mock Python — five catalog routes counting hits ──
    let search_hits = Arc::new(AtomicUsize::new(0));
    let trending_hits = Arc::new(AtomicUsize::new(0));
    let pack_hits = Arc::new(AtomicUsize::new(0));
    let install_hits = Arc::new(AtomicUsize::new(0));
    let info_hits = Arc::new(AtomicUsize::new(0));

    let s_state = search_hits.clone();
    let t_state = trending_hits.clone();
    let p_state = pack_hits.clone();
    let i_state = install_hits.clone();
    let n_state = info_hits.clone();

    let app = Router::new()
        .route(
            "/catalog/search",
            get(move |Query(q): Query<HashMap<String, String>>| {
                let counter = s_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({
                        "results": [],
                        "count": 0,
                        "echo_q": q.get("q").cloned().unwrap_or_default(),
                    }))
                }
            }),
        )
        .route(
            "/catalog/trending",
            get(move || {
                let counter = t_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({ "results": [] }))
                }
            }),
        )
        .route(
            "/catalog/pack/:name",
            post(move |Path(name): Path<String>| {
                let counter = p_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({
                        "status": "packed",
                        "path": format!("exports/{name}.kali-agent"),
                    }))
                }
            }),
        )
        .route(
            "/catalog/install",
            post(move |Json(body): Json<Value>| {
                let counter = i_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({
                        "status": "installed",
                        "path_received": body["path"].as_str().unwrap_or(""),
                    }))
                }
            }),
        )
        .route(
            "/catalog/info",
            get(move |Query(q): Query<HashMap<String, String>>| {
                let counter = n_state.clone();
                async move {
                    counter.fetch_add(1, Ordering::Relaxed);
                    Json(json!({
                        "name": "demo",
                        "echo_path": q.get("path").cloned().unwrap_or_default(),
                    }))
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

    // 1. GET /catalog/search forwards the query string.
    let resp = client
        .get(format!("http://{}/catalog/search?q=weather", rust_addr))
        .send()
        .await
        .expect("GET /catalog/search");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["echo_q"], "weather");
    assert_eq!(search_hits.load(Ordering::Relaxed), 1);

    // 2. GET /catalog/trending forwards without a body.
    let resp = client
        .get(format!("http://{}/catalog/trending", rust_addr))
        .send()
        .await
        .expect("GET /catalog/trending");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert!(body.get("results").is_some());
    assert_eq!(trending_hits.load(Ordering::Relaxed), 1);

    // 3. POST /catalog/pack/{name} forwards the path param.
    let resp = client
        .post(format!("http://{}/catalog/pack/weather-bot", rust_addr))
        .json(&json!({}))
        .send()
        .await
        .expect("POST /catalog/pack/weather-bot");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["status"], "packed");
    assert_eq!(body["path"], "exports/weather-bot.kali-agent");
    assert_eq!(pack_hits.load(Ordering::Relaxed), 1);

    // 4. POST /catalog/install forwards the JSON body.
    let resp = client
        .post(format!("http://{}/catalog/install", rust_addr))
        .json(&json!({ "path": "exports/weather-bot.kali-agent" }))
        .send()
        .await
        .expect("POST /catalog/install");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["status"], "installed");
    assert_eq!(body["path_received"], "exports/weather-bot.kali-agent");
    assert_eq!(install_hits.load(Ordering::Relaxed), 1);

    // 5. GET /catalog/info forwards the query string.
    let resp = client
        .get(format!(
            "http://{}/catalog/info?path=exports%2Fweather-bot.kali-agent",
            rust_addr
        ))
        .send()
        .await
        .expect("GET /catalog/info");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON");
    assert_eq!(body["echo_path"], "exports/weather-bot.kali-agent");
    assert_eq!(info_hits.load(Ordering::Relaxed), 1);
}
