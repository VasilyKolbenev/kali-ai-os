//! Control-plane authentication for the Rust `:3006` backend.
//!
//! Threat model: the backend may bind `0.0.0.0` when the user opts into
//! LAN access (so the mobile app can reach it). Without auth, anything on
//! the network could drive `/chat`, mutate config, install skills, etc.
//! This module adds a per-install bearer token plus an axum middleware
//! that gates non-loopback requests.
//!
//! Design:
//! - **Loopback is always exempt.** The Tauri webview talks to the backend
//!   over `127.0.0.1`/`::1`, so localhost stays friction-free (no token).
//! - **Non-loopback (LAN) requests must present the token** via either
//!   `Authorization: Bearer <token>` or `X-KALI-Token: <token>`, except for
//!   a small allowlist of read-only public paths (`/health`, `/version`).
//! - The token is generated once with a CSPRNG, persisted next to the other
//!   runtime state (`%APPDATA%/KALI` on Windows; XDG data dir elsewhere),
//!   and reused on subsequent starts.
//!
//! The mobile pairing UX (QR / manual entry) is deferred to the
//! mobile-transport work; this module only exposes the token locally
//! ([`ControlPlaneToken::value`] + the loopback-only `GET /pairing/token`
//! route) so a future pairing flow can fetch it.

use std::net::{IpAddr, SocketAddr};
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use axum::{
    extract::{ConnectInfo, Extension, Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use tracing::{info, warn};

/// Number of random bytes in the control-plane token. 32 bytes (256 bits)
/// of CSPRNG output, hex-encoded to a 64-char ASCII string.
const TOKEN_BYTES: usize = 32;

/// Read-only paths that stay reachable without a token even from the LAN.
/// Health/version expose no secrets and are useful for reachability probes
/// (e.g. a phone confirming the backend is up before pairing).
const PUBLIC_READONLY_PATHS: [&str; 2] = ["/health", "/version"];

/// Shared, immutable handle to the loaded control-plane token. Cloned into
/// the axum middleware state and the `/pairing/token` route.
#[derive(Clone)]
pub struct ControlPlaneToken(Arc<TokenInner>);

struct TokenInner {
    value: String,
    path: PathBuf,
}

impl ControlPlaneToken {
    /// The token string (hex). Exposed so a future mobile pairing flow can
    /// surface it (QR / manual). Not logged.
    pub fn value(&self) -> &str {
        &self.0.value
    }

    /// Filesystem path the token is persisted at. Handy for diagnostics and
    /// for an out-of-band pairing flow that prefers reading the file.
    pub fn path(&self) -> &std::path::Path {
        &self.0.path
    }
}

/// Resolve the token file path. `KALI_TOKEN_FILE` overrides; otherwise the
/// platform data dir (`%APPDATA%/KALI` on Windows; XDG data dir elsewhere) —
/// the same base `skills::registry` uses for `%APPDATA%/KALI/skills`.
fn resolve_token_path() -> Result<PathBuf> {
    if let Ok(p) = std::env::var("KALI_TOKEN_FILE") {
        return Ok(PathBuf::from(p));
    }
    let base = dirs::data_dir().ok_or_else(|| {
        anyhow::anyhow!("no platform data dir available — set KALI_TOKEN_FILE")
    })?;
    Ok(base.join("KALI").join("control-plane-token"))
}

/// Generate a fresh CSPRNG token (hex-encoded 256-bit value).
///
/// Uses `getrandom`, which reads directly from the OS CSPRNG
/// (`BCryptGenRandom` on Windows, `getrandom(2)`/`/dev/urandom` on Unix) —
/// not a seeded userspace PRNG. `getrandom` only fails if the OS entropy
/// source is unavailable, which on a booted desktop is effectively never;
/// we surface that as an error rather than fall back to anything weaker.
fn generate_token() -> Result<String> {
    let mut bytes = [0u8; TOKEN_BYTES];
    getrandom::getrandom(&mut bytes).context("draw CSPRNG bytes for control-plane token")?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// Persist the token with the tightest perms the platform supports.
/// Unix: `0o600` (owner read/write only). Windows: best-effort — NTFS ACL
/// tightening is out of scope, but the file lives under the user's roaming
/// profile (`%APPDATA%`), which is already per-user.
fn write_token(path: &std::path::Path, token: &str) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create token dir {}", parent.display()))?;
    }
    std::fs::write(path, token)
        .with_context(|| format!("write token file {}", path.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = std::fs::Permissions::from_mode(0o600);
        std::fs::set_permissions(path, perms)
            .with_context(|| format!("chmod 600 token file {}", path.display()))?;
    }
    Ok(())
}

/// Load the persisted token, generating + persisting one on first run.
///
/// A corrupt/empty file is treated as missing and regenerated (the token is
/// an opaque per-install secret — there is nothing to migrate, so healing it
/// is safe and keeps the backend bootable).
pub fn load_or_create() -> Result<ControlPlaneToken> {
    let path = resolve_token_path()?;
    let value = match std::fs::read_to_string(&path) {
        Ok(existing) if !existing.trim().is_empty() => existing.trim().to_string(),
        Ok(_) => {
            warn!(path = %path.display(), "control-plane token file empty — regenerating");
            let token = generate_token()?;
            write_token(&path, &token)?;
            token
        }
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            let token = generate_token()?;
            write_token(&path, &token)?;
            info!(path = %path.display(), "generated per-install control-plane token");
            token
        }
        Err(err) => {
            return Err(err)
                .with_context(|| format!("read token file {}", path.display()));
        }
    };
    Ok(ControlPlaneToken(Arc::new(TokenInner { value, path })))
}

/// True if the peer IP is loopback (`127.0.0.0/8` or `::1`), including
/// IPv4-mapped IPv6 loopback (`::ffff:127.0.0.1`).
pub(crate) fn is_loopback(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => v4.is_loopback(),
        IpAddr::V6(v6) => {
            v6.is_loopback()
                || v6
                    .to_ipv4_mapped()
                    .map(|m| m.is_loopback())
                    .unwrap_or(false)
        }
    }
}

/// Extract a presented token from `Authorization: Bearer <t>` or
/// `X-KALI-Token: <t>`. Returns `None` if neither header carries one.
fn presented_token(req: &Request) -> Option<String> {
    let headers = req.headers();
    if let Some(val) = headers.get("x-kali-token").and_then(|v| v.to_str().ok()) {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            return Some(trimmed.to_string());
        }
    }
    headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|raw| raw.strip_prefix("Bearer "))
        .map(str::trim)
        .filter(|t| !t.is_empty())
        .map(str::to_string)
}

/// Path whose upgrade may authenticate via a `?token=` query param in
/// addition to the standard headers. The mobile WebSocket client (Dart
/// `web_socket_channel`) cannot set custom headers on the upgrade, so the
/// phone connects `ws://<ip>:3006/ws?token=<token>`; HTTP routes are
/// unaffected and continue to require header auth.
const QUERY_TOKEN_PATH: &str = "/ws";

/// Extract a presented token from the URL query string (`?token=<t>` or
/// any later `&token=<t>`). Returns `None` if absent or empty. Used only
/// for the [`QUERY_TOKEN_PATH`] upgrade, where headers are unavailable.
fn query_token(req: &Request) -> Option<String> {
    let query = req.uri().query()?;
    // Safety: the raw (non-URL-decoded) value is compared directly against the stored
    // token.  This is correct only because the token is 64 hex chars [0-9a-f], which
    // are percent-encoding-invariant — encoding is a no-op.  If the token format ever
    // changes to include reserved characters (e.g. '+', '=', '/'), the server must
    // URL-decode the value before comparing.
    query
        .split('&')
        .filter_map(|pair| pair.split_once('='))
        .find(|(k, _)| *k == "token")
        .map(|(_, v)| v.trim().to_string())
        .filter(|t| !t.is_empty())
}

/// Constant-time string comparison to avoid leaking the token via timing.
fn constant_time_eq(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    let mut diff: u8 = 0;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

/// Decide whether a non-loopback request carries a valid token.
///
/// HTTP routes present the token via headers ([`presented_token`]); the
/// `/ws` upgrade may additionally present it via a `?token=` query param
/// ([`query_token`]) because the Dart WebSocket client cannot set headers.
/// Both candidates are checked in constant time against the stored token.
/// Loopback exemption is handled by the caller, not here.
fn request_token_authorized(req: &Request, expected: &str) -> bool {
    let header_ok = presented_token(req)
        .is_some_and(|presented| constant_time_eq(&presented, expected));
    if header_ok {
        return true;
    }
    if req.uri().path() == QUERY_TOKEN_PATH {
        if let Some(presented) = query_token(req) {
            return constant_time_eq(&presented, expected);
        }
    }
    false
}

fn unauthorized() -> Response {
    (
        StatusCode::UNAUTHORIZED,
        Json(json!({
            "error": {
                "code": "unauthorized",
                "message": "missing or invalid control-plane token (LAN access requires pairing)",
            }
        })),
    )
        .into_response()
}

/// axum middleware: gate non-loopback requests behind the per-install token.
///
/// - Loopback peer (`127.0.0.1`/`::1`) → always allowed (the Tauri webview).
/// - Public read-only path (`/health`, `/version`) → always allowed.
/// - Otherwise → require a matching token, else `401`.
///
/// If the peer address is unavailable (the listener was not served with
/// `into_make_service_with_connect_info::<SocketAddr>()`), we fail closed for
/// non-public paths: better to 401 a misconfigured deployment than to silently
/// run the LAN surface unauthenticated. Production `serve()` always supplies
/// connect-info, so the webview path is unaffected.
pub async fn require_token(
    State(token): State<ControlPlaneToken>,
    connect_info: Option<ConnectInfo<SocketAddr>>,
    req: Request,
    next: Next,
) -> Response {
    let path = req.uri().path();
    if PUBLIC_READONLY_PATHS.contains(&path) {
        return next.run(req).await;
    }

    match connect_info {
        Some(ConnectInfo(peer)) if is_loopback(peer.ip()) => return next.run(req).await,
        Some(ConnectInfo(_peer)) => {
            // Non-loopback: require the token. HTTP routes present it via
            // headers; the `/ws` upgrade may also present it via `?token=`
            // (the Dart WebSocket client cannot set custom headers).
            if request_token_authorized(&req, token.value()) {
                next.run(req).await
            } else {
                unauthorized()
            }
        }
        None => {
            warn!(
                %path,
                "no peer address on request — failing closed (serve without connect-info?)"
            );
            unauthorized()
        }
    }
}

/// Apply the control-plane auth layer to a built router: registers the
/// loopback-only `GET /pairing/token` seam, injects the token as an
/// `Extension` (so the pairing route can read it), and wraps everything in
/// the `require_token` middleware.
///
/// Kept separate from `http::router_full` so the existing route-contract
/// tests construct the bare router without touching the filesystem; only
/// `serve()` (and auth-focused tests) opt into the gate.
pub fn with_auth(router: axum::Router, token: ControlPlaneToken) -> axum::Router {
    router
        .route("/pairing/token", axum::routing::get(pairing_token))
        .route("/pairing/lan-ip", axum::routing::get(pairing_lan_ip))
        .layer(Extension(token.clone()))
        .layer(axum::middleware::from_fn_with_state(token, require_token))
}

/// `GET /pairing/token` — loopback-only seam for a future mobile pairing
/// flow. Returns the token + its on-disk path so the desktop can render a
/// QR / manual code.
///
/// Behind [`require_token`], a LAN caller is already turned away with `401`
/// before reaching this handler; the loopback check here is defense-in-depth
/// (and the behaviour if the route is ever mounted without the gate) — a
/// non-loopback caller that does reach it gets `404` so the endpoint is not
/// advertised off-box.
///
/// The actual mobile token-presentation + pairing UX is DEFERRED to the
/// mobile-transport work; this only makes the token retrievable locally.
pub async fn pairing_token(
    Extension(token): Extension<ControlPlaneToken>,
    connect_info: Option<ConnectInfo<SocketAddr>>,
) -> Response {
    let is_local = matches!(connect_info, Some(ConnectInfo(peer)) if is_loopback(peer.ip()));
    if !is_local {
        return StatusCode::NOT_FOUND.into_response();
    }
    (
        StatusCode::OK,
        Json(json!({
            "token": token.value(),
            "path": token.path().display().to_string(),
        })),
    )
        .into_response()
}

/// True when the backend was started LAN-exposed (`KALI_LAN=1` or an
/// explicit non-loopback `KALI_RUST_BIND`). Mirrors the precedence in
/// [`super::resolve_bind_addr`]; we re-read the env here rather than thread
/// the resolved bind address through, because the pairing view only needs a
/// boolean and the env is the single source of truth at startup.
///
/// Why this matters: the bind is fixed at `serve()` time — there is **no**
/// runtime rebind. If LAN is off, a phone cannot reach the desktop, so the
/// pairing view must tell the user to enable LAN and restart rather than
/// render an unreachable QR.
fn lan_bind_enabled() -> bool {
    if let Ok(explicit) = std::env::var("KALI_RUST_BIND") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            // Treat any non-loopback explicit bind host as LAN-exposed.
            let host = trimmed.rsplit_once(':').map(|(h, _)| h).unwrap_or(trimmed);
            let loopback = host == "127.0.0.1" || host == "::1" || host == "localhost";
            return !loopback;
        }
    }
    std::env::var("KALI_LAN")
        .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(false)
}

/// `GET /pairing/lan-ip` — loopback-only seam returning the desktop's
/// primary non-loopback LAN IPv4 plus whether the backend is actually
/// LAN-bound, so the pairing view can build the `kali://pair?ip=…` QR and
/// decide whether to show an "enable LAN + restart" prompt instead.
///
/// Loopback-only (like [`pairing_token`]): a non-loopback caller gets `404`
/// so neither the IP nor the bind state is advertised off-box.
pub async fn pairing_lan_ip(connect_info: Option<ConnectInfo<SocketAddr>>) -> Response {
    let is_local = matches!(connect_info, Some(ConnectInfo(peer)) if is_loopback(peer.ip()));
    if !is_local {
        return StatusCode::NOT_FOUND.into_response();
    }
    let ip = match local_ip_address::local_ip() {
        Ok(IpAddr::V4(v4)) => Some(v4.to_string()),
        // Prefer IPv4 for the QR; an IPv6-only result is surfaced as null so
        // the view falls back to its manual-IP hint.
        Ok(IpAddr::V6(_)) | Err(_) => None,
    };
    (
        StatusCode::OK,
        Json(json!({
            "ip": ip,
            "lan_enabled": lan_bind_enabled(),
        })),
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{Ipv4Addr, Ipv6Addr};

    #[test]
    fn generated_token_is_64_hex_chars() {
        let t = generate_token().expect("draw token");
        assert_eq!(t.len(), TOKEN_BYTES * 2);
        assert!(t.chars().all(|c| c.is_ascii_hexdigit()));
        // Two draws must differ (CSPRNG, not a constant).
        assert_ne!(t, generate_token().expect("draw token"));
    }

    #[test]
    fn loopback_detection() {
        assert!(is_loopback(IpAddr::V4(Ipv4Addr::LOCALHOST)));
        assert!(is_loopback(IpAddr::V4(Ipv4Addr::new(127, 0, 0, 5))));
        assert!(is_loopback(IpAddr::V6(Ipv6Addr::LOCALHOST)));
        // IPv4-mapped loopback.
        assert!(is_loopback(IpAddr::V6(Ipv4Addr::LOCALHOST.to_ipv6_mapped())));
        // LAN address is not loopback.
        assert!(!is_loopback(IpAddr::V4(Ipv4Addr::new(192, 168, 1, 42))));
    }

    #[test]
    fn constant_time_eq_matches_semantics() {
        assert!(constant_time_eq("abc", "abc"));
        assert!(!constant_time_eq("abc", "abd"));
        assert!(!constant_time_eq("abc", "abcd"));
        assert!(!constant_time_eq("", "x"));
    }

    /// Build a bare `GET <uri>` request (no headers) for the query-token tests.
    fn get_request(uri: &str) -> Request {
        Request::builder()
            .uri(uri)
            .body(axum::body::Body::empty())
            .expect("build request")
    }

    #[test]
    fn query_token_parses_token_param() {
        assert_eq!(
            query_token(&get_request("/ws?token=deadbeef")).as_deref(),
            Some("deadbeef")
        );
        // token after another param.
        assert_eq!(
            query_token(&get_request("/ws?foo=1&token=cafe")).as_deref(),
            Some("cafe")
        );
        // no query / no token param / empty value.
        assert_eq!(query_token(&get_request("/ws")), None);
        assert_eq!(query_token(&get_request("/ws?foo=1")), None);
        assert_eq!(query_token(&get_request("/ws?token=")), None);
    }

    #[test]
    fn ws_upgrade_accepts_valid_query_token() {
        // A header-less ws upgrade (as the Dart client sends) with the
        // correct `?token=` is authorized.
        let req = get_request("/ws?token=secret");
        assert!(request_token_authorized(&req, "secret"));
    }

    #[test]
    fn ws_upgrade_rejects_missing_or_wrong_query_token() {
        assert!(!request_token_authorized(&get_request("/ws"), "secret"));
        assert!(!request_token_authorized(
            &get_request("/ws?token=wrong"),
            "secret"
        ));
    }

    #[test]
    fn query_token_not_honored_off_the_ws_path() {
        // HTTP routes must stay header-only: a valid `?token=` on a non-ws
        // path does NOT authorize (prevents widening header auth).
        let req = get_request("/chat?token=secret");
        assert!(!request_token_authorized(&req, "secret"));
    }

    #[test]
    fn header_token_still_authorizes() {
        // HTTP header auth is unchanged for non-ws routes.
        let req = Request::builder()
            .uri("/chat")
            .header("x-kali-token", "secret")
            .body(axum::body::Body::empty())
            .expect("build request");
        assert!(request_token_authorized(&req, "secret"));
    }
}
