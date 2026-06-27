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
fn is_loopback(ip: IpAddr) -> bool {
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
            // Non-loopback: require the token.
            match presented_token(&req) {
                Some(presented) if constant_time_eq(&presented, token.value()) => {
                    next.run(req).await
                }
                _ => unauthorized(),
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
}
