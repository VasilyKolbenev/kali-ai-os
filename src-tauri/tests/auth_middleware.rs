//! WS-2 Task 2.2 — control-plane auth middleware contract.
//!
//! Verifies the loopback-exempt, token-gated behaviour of
//! `backend::auth::require_token` without needing real LAN interfaces: we
//! drive the auth-wrapped router with `tower::ServiceExt::oneshot` and inject
//! a `ConnectInfo<SocketAddr>` into each request's extensions to simulate the
//! peer IP (this is exactly the extension that
//! `into_make_service_with_connect_info::<SocketAddr>()` populates in prod).
//!
//! Cases:
//! - loopback peer, no token, mutating route → allowed (webview path)
//! - LAN peer, no token, mutating route      → 401
//! - LAN peer, correct token (Bearer)        → passes the gate
//! - LAN peer, correct token (X-KALI-Token)  → passes the gate
//! - LAN peer, no token, `/health`           → allowed (public read-only)
//! - `/pairing/token` from loopback          → 200 + token; from LAN → 401
//!   (the middleware gates it like any non-public route before the handler's
//!   own loopback-only `404` defense-in-depth even runs)

use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use axum::{
    body::Body,
    extract::ConnectInfo,
    http::{Request, StatusCode},
    routing::post,
    Router,
};
use serde_json::Value;
use tower::ServiceExt; // oneshot

use kali_desktop::backend::auth::{self, ControlPlaneToken};
use kali_desktop::backend::event_bus::EventBus;

const LOOPBACK: &str = "127.0.0.1:54321";
const LAN_PEER: &str = "192.168.1.50:54321";

/// `KALI_TOKEN_FILE` is process-wide; serialize the set-then-load section so
/// parallel tests don't clobber each other's env (same precedent as
/// `config_endpoint.rs`).
static TOKEN_ENV_LOCK: Mutex<()> = Mutex::new(());

/// Build a fresh token in a temp dir so the test never touches the real
/// `%APPDATA%/KALI` token and gets a deterministic, isolated value. The
/// returned `TempDir` must outlive the token (drop = rmdir).
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

/// Auth-wrapped router with a trivial `POST /chat` (200) so we can probe the
/// gate on a mutating route without standing up the full proxy stack.
fn app(token: ControlPlaneToken) -> Router {
    let base = Router::new()
        .route("/health", axum::routing::get(|| async { "ok" }))
        .route("/chat", post(|| async { "ok" }))
        .with_state(Arc::new(EventBus::new()));
    auth::with_auth(base, token)
}

fn req(method: &str, path: &str, peer: &str) -> Request<Body> {
    let peer: SocketAddr = peer.parse().unwrap();
    let mut r = Request::builder()
        .method(method)
        .uri(path)
        .body(Body::empty())
        .unwrap();
    // Mirror what `into_make_service_with_connect_info::<SocketAddr>()` injects.
    r.extensions_mut().insert(ConnectInfo(peer));
    r
}

async fn status_of(app: Router, req: Request<Body>) -> StatusCode {
    app.oneshot(req).await.unwrap().status()
}

#[tokio::test]
async fn loopback_mutating_route_allowed_without_token() {
    let (token, _dir) = temp_token();
    let status = status_of(app(token), req("POST", "/chat", LOOPBACK)).await;
    assert_eq!(status, StatusCode::OK, "loopback must bypass auth");
}

#[tokio::test]
async fn lan_mutating_route_rejected_without_token() {
    let (token, _dir) = temp_token();
    let status = status_of(app(token), req("POST", "/chat", LAN_PEER)).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "LAN without token must 401");
}

#[tokio::test]
async fn lan_mutating_route_allowed_with_bearer_token() {
    let (token, _dir) = temp_token();
    let value = token.value().to_string();
    let mut r = req("POST", "/chat", LAN_PEER);
    r.headers_mut().insert(
        axum::http::header::AUTHORIZATION,
        format!("Bearer {value}").parse().unwrap(),
    );
    assert_eq!(status_of(app(token), r).await, StatusCode::OK);
}

#[tokio::test]
async fn lan_mutating_route_allowed_with_x_kali_token_header() {
    let (token, _dir) = temp_token();
    let value = token.value().to_string();
    let mut r = req("POST", "/chat", LAN_PEER);
    r.headers_mut()
        .insert("x-kali-token", value.parse().unwrap());
    assert_eq!(status_of(app(token), r).await, StatusCode::OK);
}

#[tokio::test]
async fn lan_with_wrong_token_rejected() {
    let (token, _dir) = temp_token();
    let mut r = req("POST", "/chat", LAN_PEER);
    r.headers_mut().insert(
        axum::http::header::AUTHORIZATION,
        "Bearer deadbeef".parse().unwrap(),
    );
    assert_eq!(status_of(app(token), r).await, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn health_is_public_even_from_lan() {
    let (token, _dir) = temp_token();
    let status = status_of(app(token), req("GET", "/health", LAN_PEER)).await;
    assert_eq!(status, StatusCode::OK, "/health must stay open for probes");
}

#[tokio::test]
async fn pairing_token_loopback_returns_token_lan_blocked() {
    let (token, _dir) = temp_token();
    let expected = token.value().to_string();

    // Loopback → 200 + the token value + its path.
    let resp = app(token.clone())
        .oneshot(req("GET", "/pairing/token", LOOPBACK))
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let bytes = axum::body::to_bytes(resp.into_body(), 64 * 1024)
        .await
        .unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(body["token"], expected);
    assert!(body["path"].as_str().unwrap().contains("control-plane-token"));

    // LAN → 401 from the middleware (the token is unreadable off-box, which
    // is the security property that matters; the handler's loopback-only 404
    // is defense-in-depth behind the gate).
    let status = status_of(app(token), req("GET", "/pairing/token", LAN_PEER)).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}
