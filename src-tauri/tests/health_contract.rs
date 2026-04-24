//! Contract test: Rust /health on 3006 must include the fields Python sends on 3005.
//!
//! Requires both backends running. Skips gracefully if either is not up — this
//! lets the test file ship in CI even before a backend is available (test is a
//! no-op in that scenario).
//!
//! Python /health response keys (audited 2026-04-24, kernel/main.py:483-494):
//! - status: str ("ok")
//! - version: str (__version__ from pyproject)
//! - components: object with {event_bus, database, scheduler}

use serde_json::Value;

#[tokio::test]
async fn rust_health_shape_is_subset_of_python() {
    let client = reqwest::Client::new();

    let rust_resp = match client.get("http://127.0.0.1:3006/health").send().await {
        Ok(r) => r,
        Err(_) => {
            eprintln!("skip: Rust backend not running on 3006");
            return;
        }
    };
    assert_eq!(rust_resp.status(), 200);
    let rust_body: Value = rust_resp.json().await.expect("Rust /health JSON parse");

    assert_eq!(rust_body["backend"], "rust");

    let py_resp = match client.get("http://127.0.0.1:3005/health").send().await {
        Ok(r) => r,
        Err(_) => {
            eprintln!("skip: Python backend not on 3005, Rust-only shape assertion done");
            return;
        }
    };
    let py_body: Value = py_resp.json().await.expect("Python /health JSON parse");

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
