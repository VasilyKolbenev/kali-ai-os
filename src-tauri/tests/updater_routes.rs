//! /updater/status отвечает через реальный auth-обёрнутый роутер —
//! ловит ошибки wiring/сериализации, невидимые для cargo check.
use std::net::SocketAddr;
use std::sync::Mutex;

use axum::{body::Body, extract::ConnectInfo, http::Request};
use tower::ServiceExt; // oneshot

use kali_desktop::backend::auth::{self, ControlPlaneToken};
use kali_desktop::backend::http;

static TOKEN_ENV_LOCK: Mutex<()> = Mutex::new(());

fn temp_token() -> (ControlPlaneToken, tempfile::TempDir) {
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("control-plane-token");
    let token = {
        let _guard = TOKEN_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("KALI_TOKEN_FILE", &path);
        auth::load_or_create().expect("create token")
    };
    (token, dir)
}

#[tokio::test]
async fn updater_status_responds_disabled_via_real_router() {
    let (token, _dir) = temp_token();
    let app = auth::with_auth(http::router(), token);
    let peer: SocketAddr = "127.0.0.1:54321".parse().unwrap(); // loopback → auth-exempt
    let mut req = Request::builder()
        .uri("/updater/status")
        .body(Body::empty())
        .unwrap();
    req.extensions_mut().insert(ConnectInfo(peer)); // oneshot не заполняет ConnectInfo сам
    let res = app.oneshot(req).await.unwrap();
    assert_eq!(res.status(), axum::http::StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 64 * 1024)
        .await
        .unwrap();
    let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
    // OPUS-202: shipping-роутер строит production `Updater::new` → fail-closed.
    assert_eq!(v["phase"], "disabled");
    assert!(!v["reason"].as_str().unwrap_or("").is_empty());
    assert!(!v["current"].as_str().unwrap().is_empty());
}
