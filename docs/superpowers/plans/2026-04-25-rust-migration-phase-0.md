# Rust Migration Phase 0 — Scaffolding + `/health` Endpoint

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the Rust-inside-Tauri axum bridge by standing up a minimal HTTP server on port 3006 that serves `/health` with the same response shape as Python's current `/health` on 3005. Nothing else changes — Python backend continues to serve everything, UI continues to hit 3005. Phase 0 is the integration canary, not a feature.

**Architecture after this phase:**

```
Tauri main (Rust):
├── spawns kali-backend.exe (Python, port 3005)   ← unchanged
└── NEW: starts axum server (port 3006)           ← Phase 0 lives here
      └── GET /health → {same shape as Python}
```

**Tech Stack:** Rust 1.80+, Tauri 2, axum 0.7, tokio 1.x, serde 1, serde_json 1, tower-http 0.6, tracing 0.1, reqwest 0.12 (contract test only).

**Prerequisites:** `docs/superpowers/specs/2026-04-24-rust-backend-migration.md` read and agreed.

**Unblocks:** Phase 1 (stateless endpoints port `/config` `/version` `/voice/status` to Rust on 3006).

---

## Chunk 1: Cargo Dependencies + Backend Module Skeleton

### Files

- Modify: `src-tauri/Cargo.toml` — add axum, tokio, tower-http, tracing, tracing-subscriber, anyhow, thiserror.
- Create: `src-tauri/src/backend/mod.rs`
- Create: `src-tauri/src/backend/http.rs`
- Create: `src-tauri/src/backend/error.rs`

### Tasks

- [ ] **Step 1: Add Rust dependencies to `src-tauri/Cargo.toml`**

In `[dependencies]`, after the existing `ureq = "3"` line, add:

```toml
# Rust backend migration — Phase 0 onwards
axum = "0.7"
tokio = { version = "1", features = ["full"] }
tower-http = { version = "0.6", features = ["cors", "trace"] }
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
anyhow = "1"
thiserror = "1"
```

- [ ] **Step 2: Verify Cargo.toml parses**

Run: `cd src-tauri && cargo check --no-default-features`
Expected: dependency resolution succeeds. If a crate version fails to resolve, check the Rust edition in Cargo.toml (currently 2021) and bump if necessary.

- [ ] **Step 3: Create `src-tauri/src/backend/error.rs`**

```rust
use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("internal: {0}")]
    Internal(#[from] anyhow::Error),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, code, message) = match &self {
            AppError::Internal(err) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
                err.to_string(),
            ),
        };
        (
            status,
            Json(json!({
                "error": {
                    "code": code,
                    "message": message,
                }
            })),
        )
            .into_response()
    }
}

pub type AppResult<T> = Result<T, AppError>;
```

- [ ] **Step 4: Create `src-tauri/src/backend/http.rs` with `/health` handler**

```rust
use axum::{routing::get, Json, Router};
use serde::Serialize;

use crate::backend::error::AppResult;

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub version: &'static str,
    pub backend: &'static str,
}

pub async fn health() -> AppResult<Json<HealthResponse>> {
    Ok(Json(HealthResponse {
        status: "ok",
        version: env!("CARGO_PKG_VERSION"),
        backend: "rust",
    }))
}

pub fn router() -> Router {
    Router::new().route("/health", get(health))
}
```

- [ ] **Step 5: Create `src-tauri/src/backend/mod.rs`**

```rust
pub mod error;
pub mod http;

use std::net::SocketAddr;

use anyhow::Context;
use tokio::net::TcpListener;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing::info;

/// Bind address for the Phase 0 Rust backend. Python backend remains on 3005.
pub const RUST_BIND_ADDR: &str = "127.0.0.1:3006";

pub async fn serve() -> anyhow::Result<()> {
    let app = http::router()
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http());

    let addr: SocketAddr = RUST_BIND_ADDR.parse().context("parse bind address")?;
    let listener = TcpListener::bind(addr)
        .await
        .with_context(|| format!("bind {}", addr))?;
    info!("Rust backend listening on http://{}", addr);
    axum::serve(listener, app)
        .await
        .context("axum server terminated unexpectedly")?;
    Ok(())
}
```

- [ ] **Step 6: Verify backend module compiles standalone**

Run: `cd src-tauri && cargo check`
Expected: exit 0. Warnings about unused functions are OK at this stage (lib.rs hasn't imported `backend` yet).

- [ ] **Step 7: Commit Chunk 1**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/backend/
git commit -m "feat(rust-backend): add axum scaffolding for Phase 0

New backend/ module with error conversion, /health handler, and a
serve() entry point binding to 127.0.0.1:3006. Not yet wired into
Tauri lib.rs — that happens in Chunk 2."
```

---

## Chunk 2: Wire Rust Backend into Tauri Startup

### Files

- Modify: `src-tauri/src/lib.rs` — start Rust axum server alongside Python backend spawn.

### Tasks

- [ ] **Step 1: Import backend module in lib.rs**

In `src-tauri/src/lib.rs`, at the top (after the existing `use` statements), add:

```rust
mod backend;
```

- [ ] **Step 2: Initialize tracing subscriber in `run()`**

Inside `pub fn run()`, before `tauri::Builder::default()`, add:

```rust
tracing_subscriber::fmt()
    .with_env_filter(
        tracing_subscriber::EnvFilter::try_from_default_env()
            .unwrap_or_else(|_| "kali_desktop=info,tower_http=info".into()),
    )
    .init();
```

- [ ] **Step 3: Spawn Rust backend in tokio runtime inside Tauri `setup()`**

Inside the `.setup(|app| { ... })` closure, after the existing `start_backend(app.handle());` line, add:

```rust
// Phase 0: start Rust axum server on 127.0.0.1:3006 alongside Python
std::thread::spawn(|| {
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("build tokio runtime");
    if let Err(err) = rt.block_on(backend::serve()) {
        eprintln!("Rust backend exited: {:#}", err);
    }
});
```

- [ ] **Step 4: Build Tauri app in dev mode**

Run (from project root): `npm --prefix ui run build && cargo build --manifest-path src-tauri/Cargo.toml`
Expected: compilation success, may take 3-5 minutes on first build due to axum + tokio compile.

If compilation fails, read the error, fix in source, re-run. Do NOT skip this step.

- [ ] **Step 5: Start Tauri dev + verify Rust `/health` responds**

Run (from project root): `cargo run --manifest-path src-tauri/Cargo.toml -- --dev`
(Or via the existing tauri dev toolchain if configured.)

In a separate shell (keep Tauri running):
```bash
curl -s http://127.0.0.1:3006/health
```
Expected response (exact shape):
```json
{"status":"ok","version":"0.1.0","backend":"rust"}
```

Also verify Python `/health` still works:
```bash
curl -s http://127.0.0.1:3005/health
```
Expected: valid response (Python's existing shape, unchanged).

Stop Tauri dev with Ctrl+C after verification.

- [ ] **Step 6: Commit Chunk 2**

```bash
git add src-tauri/src/lib.rs
git commit -m "feat(rust-backend): wire Phase 0 axum server into Tauri startup

tracing_subscriber initialised at run() entry. Rust backend now runs
on 127.0.0.1:3006 in a dedicated tokio runtime thread, spawned from
Tauri setup() alongside the existing Python backend on 3005.

Verified: curl 3006/health returns {status,version,backend:rust},
curl 3005/health still responds (Python unchanged)."
```

---

## Chunk 3: Contract Test — Rust `/health` Response Shape Matches Python

### Files

- Create: `src-tauri/tests/health_contract.rs`

### Tasks

- [ ] **Step 1: Audit the Python `/health` response shape**

Read `kernel/main.py` and grep for the `/health` endpoint handler. Capture the exact JSON keys it returns. Write them down as a comment in the test file:

```rust
// Python /health response keys (as of 2026-04-24):
// - status: str = "ok"
// - version: str = "0.2.0-beta" (from pyproject.toml)
// - (possibly more — read the source and list them all)
```

If Python returns keys Rust does NOT, that's a migration gap to close in a later phase. For Phase 0, the Rust shape is a **subset** — status + version. Document the gap in the commit message.

- [ ] **Step 2: Write the contract test**

Create `src-tauri/tests/health_contract.rs`:

```rust
//! Contract test: Rust /health on 3006 must include the fields Python sends on 3005.
//!
//! Requires both backends running. Skips gracefully if Python on 3005 is not up —
//! this lets the test file ship in CI even before Python is available (test is a
//! no-op in that scenario).

use serde_json::Value;

#[tokio::test]
async fn rust_health_shape_is_subset_of_python() {
    let client = reqwest::Client::new();

    // Skip if Rust backend is not reachable — don't fail CI just because dev
    // forgot to start Tauri. Real verification is via manual curl in Chunk 2.
    let rust_resp = match client.get("http://127.0.0.1:3006/health").send().await {
        Ok(r) => r,
        Err(_) => {
            eprintln!("skip: Rust backend not running on 3006");
            return;
        }
    };
    assert_eq!(rust_resp.status(), 200);
    let rust_body: Value = rust_resp.json().await.expect("Rust /health JSON parse");

    // Rust must report its identity as "rust"
    assert_eq!(rust_body["backend"], "rust");

    // Python comparison (optional in CI)
    let py_resp = match client.get("http://127.0.0.1:3005/health").send().await {
        Ok(r) => r,
        Err(_) => {
            eprintln!("skip: Python backend not on 3005, Rust-only shape assertion done");
            return;
        }
    };
    let py_body: Value = py_resp.json().await.expect("Python /health JSON parse");

    // Every key Rust returns must also exist in Python (except 'backend' which
    // is a migration-only signal). Rust IS NOT required to cover everything
    // Python does yet — that's later phases.
    for key in rust_body.as_object().expect("object").keys() {
        if key == "backend" {
            continue;
        }
        assert!(
            py_body.get(key).is_some(),
            "Rust returns key '{}' that Python does not — diverging shape!",
            key
        );
    }
}
```

- [ ] **Step 3: Add `reqwest` + `tokio` to dev-dependencies**

In `src-tauri/Cargo.toml`, add:

```toml
[dev-dependencies]
reqwest = { version = "0.12", features = ["json"] }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
serde_json = "1"
```

- [ ] **Step 4: Run the contract test without backends running**

Run: `cd src-tauri && cargo test --test health_contract`
Expected: test passes with "skip: Rust backend not running" message. This is intentional — the test gracefully no-ops when backends are down.

- [ ] **Step 5: Run Tauri dev + re-run the contract test with backends running**

In terminal A: start Tauri (`cargo run --manifest-path src-tauri/Cargo.toml`).
In terminal B: `cd src-tauri && cargo test --test health_contract`.
Expected: test passes for real, comparing 3006 and 3005.

- [ ] **Step 6: Stop Tauri, commit Chunk 3**

```bash
git add src-tauri/tests/ src-tauri/Cargo.toml src-tauri/Cargo.lock
git commit -m "test(rust-backend): contract test — Rust /health shape is subset of Python

Test gracefully skips when either backend is unreachable. When both are
up, every key Rust returns (minus the new 'backend' migration marker)
must also exist in the Python response. Ensures we don't diverge shape
as Phase 0 foundations land."
```

---

## Chunk 4: UI Smoke Check — Rust Backend Visible from WebView

### Files

- No source changes. This chunk is verification-only.

### Tasks

- [ ] **Step 1: Start Tauri dev**

Run: `npm --prefix ui run dev` in one terminal (UI Vite dev server on 1420 / 1421).
Run: Tauri dev in another (uses the beforeDevCommand in tauri.conf.json, or `cargo run --manifest-path src-tauri/Cargo.toml`).

- [ ] **Step 2: Open browser DevTools in the Tauri webview**

Right-click in the KALI window → Inspect (if enabled in dev build), or add a temporary DevTools shortcut.

- [ ] **Step 3: Fetch `/health` on 3006 from the webview console**

```javascript
fetch("http://127.0.0.1:3006/health").then(r => r.json()).then(console.log)
```

Expected console output: `{ status: "ok", version: "0.1.0", backend: "rust" }`. If CORS errors appear, check `tauri.conf.json` CSP `connect-src` — it already whitelists localhost:3005 from Phase 0 Python, we need to add :3006 if not already covered.

- [ ] **Step 4: If CORS fails, extend CSP to include port 3006**

In `src-tauri/tauri.conf.json`, find the `csp` field. Add to `connect-src`:

```
http://localhost:3006 http://127.0.0.1:3006 ws://localhost:3006 ws://127.0.0.1:3006
```

Rebuild Tauri, retry Step 3.

- [ ] **Step 5: Document and commit (if CSP changed)**

If the CSP needed updating, commit separately:
```bash
git add src-tauri/tauri.conf.json
git commit -m "chore(tauri): allow localhost:3006 in CSP for Rust backend Phase 0

UI WebView needs to fetch from the new Rust backend on 3006 during
the migration window. Python backend on 3005 remains whitelisted."
```

- [ ] **Step 6: Stop Tauri dev + write the close-out note**

Phase 0 is done when:
- `cd src-tauri && cargo test` is green.
- `curl http://127.0.0.1:3006/health` returns the expected JSON with both backends running in Tauri dev.
- WebView `fetch("http://127.0.0.1:3006/health")` logs the expected response without CORS errors.
- The three chunks above are committed.

---

## Success Criteria (Phase 0 as a whole)

- ✅ axum + tokio + tower-http + tracing dependencies added; `cargo check` green.
- ✅ `src-tauri/src/backend/` module holds `/health` handler + error conversion + serve entry point.
- ✅ Rust backend listens on 127.0.0.1:3006 when Tauri starts; Python continues on 3005.
- ✅ Rust `/health` returns `{status, version, backend: "rust"}` JSON.
- ✅ Contract test verifies Rust response shape is a subset of Python's (skips when either is down).
- ✅ WebView can fetch Rust `/health` without CORS errors.
- ✅ Three-four atomic commits land on main.

**Estimated time:** 1-2 days solo. Budget extra half-day if CSP / CORS edge cases bite on Windows WebView2.

## What Comes After Phase 0

**Phase 1 (`docs/superpowers/plans/2026-05-XX-rust-migration-phase-1.md`, to be written):**
- Port `/config` (read), `/version`, `/voice/status` to Rust.
- Python continues to serve everything else.
- UI gains a simple dispatch: endpoints in the "Rust list" go to 3006, rest to 3005.
- First contract test for a non-trivial response shape.
