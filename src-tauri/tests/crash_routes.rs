//! Роуты /crash/* через РЕАЛЬНЫЙ auth-обёрнутый роутер.
//! Ключевая проверка безопасности: /crash/reveal — loopback-only (403 с LAN,
//! даже с валидным токеном), клиентский путь не принимается.
use std::net::SocketAddr;
use std::sync::Mutex;

use axum::{body::Body, extract::ConnectInfo, http::Request};
use tower::ServiceExt; // oneshot

use kali_desktop::backend::auth::{self, ControlPlaneToken};
use kali_desktop::backend::http;

const LOOPBACK: &str = "127.0.0.1:54321";
const LAN_PEER: &str = "192.168.1.50:54321";

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

fn req(method: &str, path: &str, peer: &str, token: Option<&str>) -> Request<Body> {
    let peer: SocketAddr = peer.parse().unwrap();
    let mut b = Request::builder().method(method).uri(path);
    if let Some(t) = token {
        b = b.header("X-KALI-Token", t);
    }
    let mut r = b.body(Body::empty()).unwrap();
    // oneshot не заполняет ConnectInfo сам (в проде это делает
    // into_make_service_with_connect_info)
    r.extensions_mut().insert(ConnectInfo(peer));
    r
}

#[tokio::test]
async fn crash_status_answers_with_backend_alive_flag() {
    let (token, _dir) = temp_token();
    let app = auth::with_auth(http::router(), token);
    let res = app
        .oneshot(req("GET", "/crash/status", LOOPBACK, None))
        .await
        .unwrap();
    assert_eq!(res.status(), axum::http::StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 64 * 1024).await.unwrap();
    let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
    // Python в тестах не запущен → false; главное, что поле есть и это bool
    assert!(v["backend_alive"].is_boolean(), "нет backend_alive: {v}");
}

#[tokio::test]
async fn crash_reveal_is_rejected_from_lan_even_with_token() {
    let (token, _dir) = temp_token();
    let token_value = token.value().to_string();
    let app = auth::with_auth(http::router(), token);
    let res = app
        .oneshot(req("POST", "/crash/reveal", LAN_PEER, Some(&token_value)))
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        axum::http::StatusCode::FORBIDDEN,
        "reveal обязан быть loopback-only даже с валидным токеном"
    );
}
