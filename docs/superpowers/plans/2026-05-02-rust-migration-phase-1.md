# Rust Migration Phase 1 — Stateless Endpoints

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port three read-heavy, low-state endpoints from Python FastAPI to Rust axum on port 3006: `/version` (new), `/config` (existing Python shape preserved), `/voice/status` (proxied to Python until Phase 3 migrates the pipeline). Build the UI-side dispatcher that routes migrated endpoints to Rust while keeping everything else on Python. Phase 1 is the first time real user-facing traffic flows through Rust.

**Architecture delta after this phase:**

```
Before Phase 1:
  UI → http://127.0.0.1:3005 (Python FastAPI, everything)
  Rust /health on 3006 (contract-test target only)

After Phase 1:
  UI → dispatcher:
         /health      → 3006 (Rust native)
         /version     → 3006 (Rust native — new endpoint)
         /config      → 3006 (Rust native, serde_yaml)
         /voice/status → 3006 (Rust proxy → Python 3005)
         everything else → 3005 (Python, unchanged)
  Python backend — unchanged, still authoritative for unmigrated endpoints.
```

**Tech stack addition:**
- `serde_yaml` 0.9 — deserialise `config/kali.yaml` in Rust.
- `reqwest` is already dev-dep; promote to main dep for the proxy.
- No UI library changes — dispatcher is plain TypeScript.

**Prerequisites:**
- Phase 0 landed (`docs/superpowers/plans/2026-04-25-rust-migration-phase-0.md`). Rust backend boots on 3006, `/health` works, CSP allows 3006.
- Spec read: `docs/superpowers/specs/2026-04-24-rust-backend-migration.md` §5-§8 (module map, HTTP contract, error handling).

**Unblocks:**
- Plan 3 (Onboarding flow) — needs `/config` readable without editing `.env`.
- Plan 4 (Settings UI) — will add `/config` write endpoint in Phase 1.5 or Phase 2, building on this foundation.

---

## Chunk 1: UI Endpoint Dispatcher

**What:** Introduce a lightweight routing layer in the UI that sends a declared allow-list of paths to the Rust backend (3006) and everything else to Python (3005). No backend changes here — purely frontend preparation.

### Files

- Modify: `ui/src/api/runtime.ts` — add `rustApiBaseUrl` + `rustApiUrl()` helper.
- Create: `ui/src/api/endpoints.ts` — the RUST_ENDPOINTS allow-list + dispatcher function.
- Create: `ui/src/api/__tests__/endpoints.test.ts`
- Modify: `ui/src/api/client.ts` — switch `/health` (if used) and any already-ready endpoints to `rustApiUrl`.

### Tasks

- [ ] **Step 1: Extend `ui/src/api/runtime.ts` with Rust base URL**

Add after the `apiBaseUrl` export:

```typescript
export const rustApiBaseUrl = trimTrailingSlash(
  env.VITE_KALI_RUST_API_BASE_URL ||
    runtimeConfig?.apiBaseUrl?.replace(/:3005$/, ":3006") ||
    "http://127.0.0.1:3006",
);

export function rustApiUrl(path: string): string {
  return `${rustApiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}
```

Also extend the `Window.__KALI_CONFIG__` declaration with an optional `rustApiBaseUrl?: string;` field so production overrides work.

- [ ] **Step 2: Write the failing dispatcher test**

Create `ui/src/api/__tests__/endpoints.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { resolveApiUrl, RUST_ENDPOINTS } from "../endpoints";

describe("endpoint dispatcher", () => {
  it("routes RUST_ENDPOINTS paths to the Rust backend", () => {
    for (const path of RUST_ENDPOINTS) {
      const url = resolveApiUrl(path);
      expect(url).toContain(":3006");
    }
  });

  it("routes unmigrated paths to Python", () => {
    const url = resolveApiUrl("/skills");
    expect(url).toContain(":3005");
  });

  it("is stable on query strings and trailing slashes", () => {
    expect(resolveApiUrl("/config?reload=1")).toContain(":3006");
    expect(resolveApiUrl("/skills/")).toContain(":3005");
  });
});
```

- [ ] **Step 3: Run the test — verify it fails**

Run: `cd ui && pnpm test -- src/api/__tests__/endpoints.test.ts`
Expected: FAIL — "Cannot find module '../endpoints'".

- [ ] **Step 4: Implement `ui/src/api/endpoints.ts`**

```typescript
import { apiUrl, rustApiUrl } from "./runtime";

/**
 * Paths served by the Rust backend on port 3006.
 * Grows as endpoints migrate from Python. Everything else goes to 3005.
 */
export const RUST_ENDPOINTS: readonly string[] = [
  "/health",
  "/version",
  "/config",
  "/voice/status",
] as const;

function pathOf(input: string): string {
  const withSlash = input.startsWith("/") ? input : `/${input}`;
  const qIndex = withSlash.indexOf("?");
  const path = qIndex === -1 ? withSlash : withSlash.slice(0, qIndex);
  return path.endsWith("/") && path.length > 1 ? path.slice(0, -1) : path;
}

export function resolveApiUrl(path: string): string {
  return RUST_ENDPOINTS.includes(pathOf(path)) ? rustApiUrl(path) : apiUrl(path);
}
```

- [ ] **Step 5: Run the test — verify it passes**

Run: `cd ui && pnpm test -- src/api/__tests__/endpoints.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 6: Update `ui/src/api/client.ts` to use the dispatcher**

In `ui/src/api/client.ts`, locate `fetchJSON` (or equivalent helper) and change it to use `resolveApiUrl(path)` instead of `apiUrl(path)`. If fetchJSON is imported from runtime, extend it in runtime.ts instead — pick whichever fits the existing pattern.

After the change, every call in client.ts automatically routes correctly via the allow-list. No per-endpoint edits in client.ts are needed.

Verify: `cd ui && npx tsc --noEmit` exits 0.

- [ ] **Step 7: Run the full UI test suite**

Run: `cd ui && pnpm test`
Expected: all 20+ tests pass (new endpoint tests + existing suite).

- [ ] **Step 8: Preview smoke check — dispatcher doesn't break UI**

Start preview, verify app loads, console has no errors, `/health` (if the UI probes it) resolves via :3006 (check Network tab if available via eval).

Quick eval:
```javascript
await fetch("/health").then(r => r.url)
```

Should return a URL containing `:3006`. Actually `fetch("/health")` with relative path ignores our dispatcher — the dispatcher is only active through the `client.ts` API object. Real test: call `api.voiceStatus()` via eval and inspect the Network tab (or use `preview_network` tool).

Alternative: use `preview_network` to verify the request went to :3006 when UI loads.

- [ ] **Step 9: Commit**

```bash
git add ui/src/api/runtime.ts ui/src/api/endpoints.ts ui/src/api/__tests__/ ui/src/api/client.ts
git commit -m "feat(ui): endpoint dispatcher for Rust/Python migration

RUST_ENDPOINTS allow-list in ui/src/api/endpoints.ts. client.ts uses
resolveApiUrl() which routes allow-listed paths to 3006 (Rust) and
everything else to 3005 (Python). As endpoints migrate, they're added
to the allow-list — one-line change per endpoint.

3 tests cover: allow-listed paths hit :3006, unmigrated hit :3005,
routing is stable on query strings and trailing slashes."
```

---

## Chunk 2: `/version` Endpoint in Rust

**What:** Add a new `/version` endpoint in Rust that returns the app's semantic version, build profile, and git commit hash. This is the simplest migration target — zero Python equivalent to match, pure Rust implementation.

### Files

- Modify: `src-tauri/Cargo.toml` — add build-time git hash capture (no new deps, use `env!` of `CARGO_PKG_VERSION`).
- Modify: `src-tauri/src/backend/http.rs` — add `/version` handler.
- Create: `src-tauri/tests/version_endpoint.rs` — integration test.

### Tasks

- [ ] **Step 1: Write the failing integration test**

Create `src-tauri/tests/version_endpoint.rs`:

```rust
//! Integration test for /version. Spawns a minimal axum instance on an
//! ephemeral port and hits it via reqwest — no Tauri, no Python required.

use axum::Router;
use serde_json::Value;
use std::net::SocketAddr;
use tokio::net::TcpListener;

async fn start_test_server() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn version_returns_semantic_shape() {
    let addr = start_test_server().await;
    let url = format!("http://{}/version", addr);

    let resp = reqwest::get(&url).await.expect("GET /version");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON parse");

    assert!(body["version"].is_string());
    assert!(body["build_profile"].is_string());
    // Commit hash may be unknown in some build contexts — accept null or string.
    assert!(body["commit"].is_string() || body["commit"].is_null());
}
```

- [ ] **Step 2: Make `backend` module public in lib.rs**

In `src-tauri/src/lib.rs`, change the declaration:
```rust
mod backend;
```
to:
```rust
pub mod backend;
```
This lets integration tests reach `kali_desktop::backend::http::router()`.

- [ ] **Step 3: Run the test — verify it fails**

Run: `cd src-tauri && cargo test --test version_endpoint`
Expected: FAIL — either compilation error (`/version` route missing) or runtime 404.

- [ ] **Step 4: Implement the `/version` handler**

In `src-tauri/src/backend/http.rs`, add:

```rust
#[derive(Serialize)]
pub struct VersionResponse {
    pub version: &'static str,
    pub build_profile: &'static str,
    pub commit: Option<&'static str>,
}

pub async fn version() -> AppResult<Json<VersionResponse>> {
    Ok(Json(VersionResponse {
        version: env!("CARGO_PKG_VERSION"),
        build_profile: if cfg!(debug_assertions) { "debug" } else { "release" },
        commit: option_env!("KALI_GIT_COMMIT"),
    }))
}
```

Extend `pub fn router()`:
```rust
pub fn router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/version", get(version))
}
```

- [ ] **Step 5: Run the test — verify it passes**

Run: `cd src-tauri && cargo test --test version_endpoint`
Expected: PASS.

- [ ] **Step 6: (Optional) capture git commit via build.rs**

If `KALI_GIT_COMMIT` is not set at build time, `commit` is null. Optionally populate it. In `src-tauri/build.rs` (already exists for `tauri-build`), append:

```rust
// Capture short git commit for /version endpoint (best-effort).
if let Ok(output) = std::process::Command::new("git")
    .args(["rev-parse", "--short", "HEAD"])
    .output()
{
    if output.status.success() {
        let hash = String::from_utf8_lossy(&output.stdout).trim().to_string();
        println!("cargo:rustc-env=KALI_GIT_COMMIT={}", hash);
    }
}
```

Re-run `cargo test --test version_endpoint` to confirm it still passes.

- [ ] **Step 7: Commit**

```bash
git add src-tauri/src/backend/http.rs src-tauri/src/lib.rs src-tauri/tests/version_endpoint.rs src-tauri/build.rs
git commit -m "feat(rust-backend): /version endpoint

Returns {version, build_profile, commit}. Git commit captured at build
time via build.rs, falls back to null when git isn't available.
Integration test spawns axum on ephemeral port, verifies shape."
```

---

## Chunk 3: `/config` Endpoint in Rust (reads config/kali.yaml)

**What:** Port the read side of `/config` from Python. The Rust handler loads `config/kali.yaml` via serde_yaml and returns JSON matching Python's `model_dump()` output shape. Write side (POST `/config`) stays in Python for Phase 1 — moves later.

### Files

- Modify: `src-tauri/Cargo.toml` — add `serde_yaml` dep.
- Create: `src-tauri/src/backend/config.rs` — config loading + serialisation.
- Modify: `src-tauri/src/backend/http.rs` — add `/config` handler.
- Create: `src-tauri/tests/config_endpoint.rs` — integration test.

### Tasks

- [ ] **Step 1: Add `serde_yaml` dependency**

In `src-tauri/Cargo.toml` `[dependencies]`, after `serde_json`:
```toml
serde_yaml = "0.9"
```
Run: `cd src-tauri && cargo check` — expect exit 0.

- [ ] **Step 2: Audit Python config shape**

Read `kernel/models.py` and `config/kali.yaml` to understand the shape Python returns. Capture the top-level keys and their field types. As of 2026-04-24:

```yaml
server: { host: str, port: int }
voice: { wake_word: str, mode: str, stt_model: str, tts_voice: str, vad_threshold: float, auto_start: bool }
llm: { cloud_provider: str, cloud_model: str, local_provider: str, local_model: str, auto_route: bool }
schedule: { morning_hour: int, evening_hour: int }
```

If the actual file has more keys when this plan runs, list them all — Rust must mirror every field.

- [ ] **Step 3: Write the failing integration test**

Create `src-tauri/tests/config_endpoint.rs`:

```rust
//! Integration test for GET /config.
//!
//! Requires config/kali.yaml to exist at repo root relative to cwd, or via
//! the KALI_CONFIG env var. Test sets KALI_CONFIG to a fixture path.

use axum::Router;
use serde_json::Value;
use std::net::SocketAddr;
use tokio::net::TcpListener;

async fn start_test_server() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn config_returns_yaml_as_json() {
    // Point KALI_CONFIG to the real config in the repo
    std::env::set_var("KALI_CONFIG", "../config/kali.yaml");

    let addr = start_test_server().await;
    let url = format!("http://{}/config", addr);

    let resp = reqwest::get(&url).await.expect("GET /config");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("JSON parse");

    // Top-level keys must match Python's model_dump output
    for key in ["server", "voice", "llm", "schedule"] {
        assert!(body.get(key).is_some(), "missing top-level key '{}'", key);
    }
    // Spot-check nested field types
    assert!(body["voice"]["mode"].is_string());
    assert!(body["voice"]["auto_start"].is_boolean());
    assert!(body["server"]["port"].is_number());
}
```

- [ ] **Step 4: Run the test — verify it fails**

Run: `cd src-tauri && cargo test --test config_endpoint`
Expected: FAIL — 404 on /config.

- [ ] **Step 5: Implement `src-tauri/src/backend/config.rs`**

```rust
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

/// Top-level application config, mirroring kernel/models.py AppConfig shape.
/// Field names and types must match Python's model_dump output so existing
/// UI consumers don't need to change.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct AppConfig {
    pub server: ServerConfig,
    pub voice: VoiceConfig,
    pub llm: LlmConfig,
    pub schedule: ScheduleConfig,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct VoiceConfig {
    pub wake_word: String,
    pub mode: String,
    pub stt_model: String,
    pub tts_voice: String,
    pub vad_threshold: f32,
    pub auto_start: bool,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct LlmConfig {
    pub cloud_provider: String,
    pub cloud_model: String,
    pub local_provider: String,
    pub local_model: String,
    pub auto_route: bool,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ScheduleConfig {
    pub morning_hour: u8,
    pub evening_hour: u8,
}

pub fn resolve_config_path() -> PathBuf {
    std::env::var("KALI_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("../config/kali.yaml"))
}

pub fn load_from(path: &Path) -> Result<AppConfig> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("read config from {:?}", path))?;
    serde_yaml::from_str::<AppConfig>(&raw).with_context(|| format!("parse config at {:?}", path))
}

pub fn load() -> Result<AppConfig> {
    load_from(&resolve_config_path())
}
```

- [ ] **Step 6: Wire `/config` handler**

In `src-tauri/src/backend/http.rs`, add:

```rust
use crate::backend::config;

pub async fn get_config() -> AppResult<Json<config::AppConfig>> {
    let cfg = config::load().map_err(Into::into)?;
    Ok(Json(cfg))
}
```

Extend `router()`:
```rust
.route("/config", get(get_config))
```

In `src-tauri/src/backend/mod.rs`, add:
```rust
pub mod config;
```

- [ ] **Step 7: Run the test — verify it passes**

Run: `cd src-tauri && cargo test --test config_endpoint`
Expected: PASS.

- [ ] **Step 8: Live contract test against Python**

In one terminal, start Tauri dev (which spawns Python backend).
In another:
```bash
curl -s http://127.0.0.1:3005/config > /tmp/py-config.json
curl -s http://127.0.0.1:3006/config > /tmp/rust-config.json
diff <(jq -S . /tmp/py-config.json) <(jq -S . /tmp/rust-config.json)
```
Expected: zero diff. If Python emits fields the YAML doesn't have (e.g. computed defaults), either add them to the Rust struct with `#[serde(default)]` or document them in the commit message.

- [ ] **Step 9: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/backend/config.rs src-tauri/src/backend/mod.rs src-tauri/src/backend/http.rs src-tauri/tests/config_endpoint.rs
git commit -m "feat(rust-backend): /config endpoint reads kali.yaml natively

serde_yaml deserialises config/kali.yaml into strongly-typed AppConfig
matching kernel/models.py shape. Integration test asserts top-level keys
and nested field types. Live diff against Python confirms byte-identical
JSON output.

Write side (POST /config) stays in Python for Phase 1, migrates later."
```

---

## Chunk 4: `/voice/status` Proxy to Python

**What:** Implement a proxy: Rust receives GET `/voice/status`, forwards to Python `/voice/status` on 3005, streams the response back unchanged. This lets the UI dispatcher route voice endpoints to 3006 consistently without waiting for Phase 3 to migrate the pipeline. When Phase 3 lands, the handler swaps from proxy to native — no UI change.

### Files

- Modify: `src-tauri/Cargo.toml` — promote `reqwest` from dev-dep to runtime dep.
- Create: `src-tauri/src/backend/proxy.rs` — generic proxy helper.
- Modify: `src-tauri/src/backend/http.rs` — add `/voice/status` route.
- Create: `src-tauri/tests/voice_status_proxy.rs` — mock-Python integration test.

### Tasks

- [ ] **Step 1: Promote `reqwest` to runtime dependency**

In `src-tauri/Cargo.toml` `[dependencies]` (not `[dev-dependencies]`), add:

```toml
reqwest = { version = "0.12", features = ["json", "stream"] }
```

Remove the duplicate entry from `[dev-dependencies]` — it inherits from runtime deps.

Run: `cd src-tauri && cargo check` — expect exit 0.

- [ ] **Step 2: Write the failing proxy test**

Create `src-tauri/tests/voice_status_proxy.rs`:

```rust
//! Proxy test: start a mock Python on an ephemeral port, point the Rust
//! proxy at it, verify Rust forwards request and response faithfully.

use axum::{routing::get, Json, Router};
use serde_json::{json, Value};
use std::net::SocketAddr;
use tokio::net::TcpListener;

async fn start_mock_python() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/voice/status",
        get(|| async {
            Json(json!({
                "available": true,
                "ready": true,
                "started": false,
                "state": "idle",
                "mode": "wake_word",
                "models_ready": true,
                "missing_models": []
            }))
        }),
    );
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
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app: Router = kali_desktop::backend::http::router();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn voice_status_proxies_to_python() {
    let py_addr = start_mock_python().await;
    let rust_addr = start_rust_with_python(py_addr).await;

    let resp = reqwest::get(format!("http://{}/voice/status", rust_addr))
        .await
        .expect("GET /voice/status");
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await.expect("JSON parse");
    assert_eq!(body["mode"], "wake_word");
    assert_eq!(body["state"], "idle");
    assert_eq!(body["available"], true);
}
```

- [ ] **Step 3: Implement `src-tauri/src/backend/proxy.rs`**

```rust
use anyhow::{Context, Result};
use reqwest::Client;

pub fn python_backend_url() -> String {
    std::env::var("KALI_PYTHON_BACKEND_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:3005".to_string())
}

/// Proxy a GET request to the Python backend and return the response body.
/// Streaming is not used here — voice/status payload is tiny. For large
/// responses (TTS audio), revisit when those endpoints migrate.
pub async fn proxy_get_json(path: &str) -> Result<serde_json::Value> {
    let base = python_backend_url();
    let url = format!("{}{}", base, path);
    let client = Client::new();
    let resp = client
        .get(&url)
        .send()
        .await
        .with_context(|| format!("GET {}", url))?;
    let status = resp.status();
    if !status.is_success() {
        anyhow::bail!("Python backend returned {} for {}", status, url);
    }
    resp.json::<serde_json::Value>()
        .await
        .with_context(|| format!("parse JSON from {}", url))
}
```

Add `pub mod proxy;` to `src-tauri/src/backend/mod.rs`.

- [ ] **Step 4: Add `/voice/status` handler in `http.rs`**

```rust
use crate::backend::proxy;

pub async fn voice_status() -> AppResult<Json<serde_json::Value>> {
    let body = proxy::proxy_get_json("/voice/status")
        .await
        .map_err(Into::into)?;
    Ok(Json(body))
}
```

Extend `router()`:
```rust
.route("/voice/status", get(voice_status))
```

- [ ] **Step 5: Run the test — verify it passes**

Run: `cd src-tauri && cargo test --test voice_status_proxy`
Expected: PASS.

- [ ] **Step 6: Live smoke — Rust proxy with real Python**

Start Tauri dev (spawns Python). In another shell:
```bash
curl -s http://127.0.0.1:3005/voice/status > /tmp/py-vs.json
curl -s http://127.0.0.1:3006/voice/status > /tmp/rust-vs.json
diff <(jq -S . /tmp/py-vs.json) <(jq -S . /tmp/rust-vs.json)
```
Expected: zero diff. Python's response flows through Rust untouched.

- [ ] **Step 7: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/backend/proxy.rs src-tauri/src/backend/mod.rs src-tauri/src/backend/http.rs src-tauri/tests/voice_status_proxy.rs
git commit -m "feat(rust-backend): /voice/status proxies to Python via reqwest

Generic proxy_get_json helper forwards GET requests to the Python
backend (KALI_PYTHON_BACKEND_URL env var, defaults to 127.0.0.1:3005).
/voice/status handler uses it. Mock-Python integration test confirms
the proxy produces byte-identical output. Handler will swap from proxy
to native when Phase 3 migrates the voice pipeline — no UI change then."
```

---

## Chunk 5: Contract Tests + UI End-to-End Verification

**What:** Expand the existing `health_contract.rs` into a multi-endpoint contract test that validates every migrated endpoint against its Python counterpart (when both are live). Run a UI smoke test confirming the dispatcher actually routes /config and /voice/status to 3006 in browser.

### Files

- Modify: `src-tauri/tests/health_contract.rs` → rename to `tests/endpoints_contract.rs`, extend to cover `/version`, `/config`, `/voice/status`.
- No UI code changes; verification only.

### Tasks

- [ ] **Step 1: Rename and expand the contract test**

Rename `src-tauri/tests/health_contract.rs` → `src-tauri/tests/endpoints_contract.rs`. Change the test function to a `mod` of tests:

```rust
//! Contract tests: every migrated endpoint's Rust response shape must be
//! a subset of Python's. Tests skip gracefully when either backend is down.

use serde_json::Value;

async fn fetch_json(url: &str) -> Option<Value> {
    reqwest::Client::new()
        .get(url)
        .send()
        .await
        .ok()?
        .json::<Value>()
        .await
        .ok()
}

fn assert_rust_keys_subset_of_python(rust: &Value, py: &Value, ignore_keys: &[&str]) {
    for (key, _) in rust.as_object().expect("Rust must be JSON object") {
        if ignore_keys.contains(&key.as_str()) {
            continue;
        }
        assert!(
            py.get(key).is_some(),
            "Rust returns key '{}' that Python does not — diverging shape!",
            key
        );
    }
}

#[tokio::test]
async fn health_shape_subset() {
    let rust = match fetch_json("http://127.0.0.1:3006/health").await {
        Some(v) => v,
        None => { eprintln!("skip: Rust :3006 down"); return; }
    };
    assert_eq!(rust["backend"], "rust");
    let py = match fetch_json("http://127.0.0.1:3005/health").await {
        Some(v) => v,
        None => { eprintln!("skip: Python :3005 down"); return; }
    };
    assert_rust_keys_subset_of_python(&rust, &py, &["backend"]);
}

#[tokio::test]
async fn config_shape_matches() {
    let rust = match fetch_json("http://127.0.0.1:3006/config").await {
        Some(v) => v,
        None => { eprintln!("skip: Rust :3006 down"); return; }
    };
    let py = match fetch_json("http://127.0.0.1:3005/config").await {
        Some(v) => v,
        None => { eprintln!("skip: Python :3005 down"); return; }
    };
    // For /config we want bidirectional shape-equality: Rust must NOT drop
    // any key Python sends, and must NOT invent any.
    assert_rust_keys_subset_of_python(&rust, &py, &[]);
    assert_rust_keys_subset_of_python(&py, &rust, &[]);
}

#[tokio::test]
async fn voice_status_shape_matches() {
    let rust = match fetch_json("http://127.0.0.1:3006/voice/status").await {
        Some(v) => v,
        None => { eprintln!("skip: Rust :3006 down"); return; }
    };
    let py = match fetch_json("http://127.0.0.1:3005/voice/status").await {
        Some(v) => v,
        None => { eprintln!("skip: Python :3005 down"); return; }
    };
    // Proxy path — must match byte-for-byte (modulo tokio ordering)
    assert_rust_keys_subset_of_python(&rust, &py, &[]);
    assert_rust_keys_subset_of_python(&py, &rust, &[]);
}

#[tokio::test]
async fn version_is_rust_only() {
    let rust = match fetch_json("http://127.0.0.1:3006/version").await {
        Some(v) => v,
        None => { eprintln!("skip: Rust :3006 down"); return; }
    };
    assert!(rust["version"].is_string());
    assert!(rust["build_profile"].is_string());
    // Python has no /version endpoint — don't attempt comparison.
}
```

- [ ] **Step 2: Run the contract suite without backends**

Run: `cd src-tauri && cargo test --test endpoints_contract`
Expected: 4 tests pass with "skip" messages. No assertions fire.

- [ ] **Step 3: Start Tauri dev + re-run contract suite**

Start Tauri (both backends come up). In another terminal:
```bash
cd src-tauri && cargo test --test endpoints_contract
```
Expected: 4 tests pass with real assertions. If `config_shape_matches` fails with "Python sends key X that Rust drops", extend `AppConfig` struct (Chunk 3) to include that field. If `voice_status_shape_matches` fails, investigate — proxy should produce identical output.

- [ ] **Step 4: UI dispatcher verification**

In Tauri dev, open DevTools Network tab. Trigger `api.voiceStatus()` (e.g., via Settings mode or `api.config()` from eval). Confirm the request URL shows `127.0.0.1:3006`. If it still shows :3005, the dispatcher wiring in `client.ts` (Chunk 1 Step 6) was missed — revisit.

Alternative via `preview_network`:
```javascript
await (await fetch("/voice/status", { method: "POST" }).catch(() => fetch("/voice/status"))).url
```
Expected: contains `:3006`.

- [ ] **Step 5: Commit**

```bash
git add src-tauri/tests/
git commit -m "test(rust-backend): expand contract tests to all Phase 1 endpoints

Covers /health /version /config /voice/status. Config and proxied voice
status require BIDIRECTIONAL shape equality — Rust must not drop or
invent keys vs Python. Health keeps subset-only (intentional shape
divergence during migration — Rust omits components.* until Phase 3).

All tests skip gracefully when either backend is unreachable, so the
suite works in CI without infrastructure."
```

---

## Success Criteria (Phase 1 as a whole)

- ✅ UI dispatcher routes `/health`, `/version`, `/config`, `/voice/status` to 3006; everything else to 3005. Unit-tested.
- ✅ `/version` endpoint live on Rust, returns `{version, build_profile, commit}`.
- ✅ `/config` endpoint live on Rust, reads `config/kali.yaml`, returns JSON byte-identical to Python.
- ✅ `/voice/status` endpoint live on Rust, proxies to Python transparently.
- ✅ Contract test suite (4 tests) passes with both backends running.
- ✅ UI in dev mode sends `/config` and `/voice/status` requests to :3006, no regressions visible.
- ✅ 5 atomic commits land on main.

**Estimated time:** 4-7 days solo. Largest time sink: Chunk 3 if Python's `model_dump` emits fields not declared in YAML (requires iterating the Rust struct until `config_shape_matches` passes bidirectionally).

## What Comes After Phase 1

**Phase 2 plan (`docs/superpowers/plans/2026-05-XX-rust-migration-phase-2.md`, written after Phase 1 closes):**
- Port Python's WebSocket handler (`/ws`) to Rust — this is where the event bus migration starts.
- Rust event bus (`tokio::sync::broadcast`) publishes the same events UI expects (`voice.state`, `voice.pipeline`, etc.).
- Python publishes into the Rust event bus via a "push" bridge — when voice pipeline state changes in Python, it sends a message to Rust; Rust fans out to WebSocket subscribers.
- Unblocks Feedback-channel plan (Tier 1 #6).

## Risks & Mitigations (Phase 1-specific)

| Risk | Likelihood | Mitigation |
|---|---|---|
| `AppConfig` struct drifts from Python `model_dump` shape | Med | Bidirectional contract test catches every divergence; fix by extending the struct. |
| reqwest blocks on DNS in test runs | Low | Tests use `127.0.0.1` directly, no DNS. |
| Proxy latency adds up | Low | Each hop is ~1-3 ms local, invisible to user. Measure only if user reports lag. |
| CSP blocks :3006 fetches in packaged build | Low | Chunk 4 of Phase 0 already allowed :3006. Verify once in packaged build before closing Phase 1. |
| Python /config includes computed fields absent from YAML | Med | Extend Rust `AppConfig` with `#[serde(default)]` + populate in handler. If field is truly computed (not stored), add post-deserialization logic in `config::load`. |
