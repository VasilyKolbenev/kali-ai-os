//! Contract tests: every migrated endpoint's Rust response shape must be
//! a subset of Python's (or bidirectionally equal for ported endpoints).
//! Tests skip gracefully when either backend is unreachable, so the suite
//! works in CI without infrastructure.
//!
//! Python /health audit (kernel/main.py:483-494): {status, version, components}
//! Python /config audit (kernel/main.py:504-506): config_manager.config.model_dump()
//! Python /voice/status audit (kernel/main.py:508-520): pipeline state + model readiness

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
        None => {
            eprintln!("skip: Rust :3006 down");
            return;
        }
    };
    assert_eq!(rust["backend"], "rust");
    let py = match fetch_json("http://127.0.0.1:3005/health").await {
        Some(v) => v,
        None => {
            eprintln!("skip: Python :3005 down");
            return;
        }
    };
    // `backend` and `ws_subscribers` are Rust-only (Phase 0/2 additions).
    assert_rust_keys_subset_of_python(&rust, &py, &["backend", "ws_subscribers"]);
}

#[tokio::test]
async fn config_shape_matches_bidirectionally() {
    let rust = match fetch_json("http://127.0.0.1:3006/config").await {
        Some(v) => v,
        None => {
            eprintln!("skip: Rust :3006 down");
            return;
        }
    };
    let py = match fetch_json("http://127.0.0.1:3005/config").await {
        Some(v) => v,
        None => {
            eprintln!("skip: Python :3005 down");
            return;
        }
    };
    assert_rust_keys_subset_of_python(&rust, &py, &[]);
    assert_rust_keys_subset_of_python(&py, &rust, &[]);
}

#[tokio::test]
async fn voice_status_shape_matches_bidirectionally() {
    let rust = match fetch_json("http://127.0.0.1:3006/voice/status").await {
        Some(v) => v,
        None => {
            eprintln!("skip: Rust :3006 down");
            return;
        }
    };
    let py = match fetch_json("http://127.0.0.1:3005/voice/status").await {
        Some(v) => v,
        None => {
            eprintln!("skip: Python :3005 down");
            return;
        }
    };
    assert_rust_keys_subset_of_python(&rust, &py, &[]);
    assert_rust_keys_subset_of_python(&py, &rust, &[]);
}

#[tokio::test]
async fn version_is_rust_only() {
    let rust = match fetch_json("http://127.0.0.1:3006/version").await {
        Some(v) => v,
        None => {
            eprintln!("skip: Rust :3006 down");
            return;
        }
    };
    assert!(rust["version"].is_string());
    assert!(rust["build_profile"].is_string());
}
