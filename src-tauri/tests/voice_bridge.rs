//! End-to-end bridge test: spawn `kernel.workers.tts_worker`, send a `ping`
//! op via `BridgeWorker`, expect `{"pong": true}` reply within the window.
//! Validates the JSON envelope wire format on a real child process — no
//! mock — so the writer/reader/correlation map all run on real bytes.

use std::time::Duration;

use serde_json::json;

use kali_desktop::backend::voice::bridge::BridgeWorker;

fn python_executable() -> String {
    std::env::var("KALI_PY").unwrap_or_else(|_| "../.venv/Scripts/python.exe".to_string())
}

#[tokio::test]
async fn bridge_ping_round_trip() {
    let worker = BridgeWorker::spawn(
        "tts_test",
        python_executable(),
        &["-m", "kernel.workers.tts_worker"],
        "..", // tests run from src-tauri/; kernel package lives one up
    )
    .await
    .expect("spawn worker");

    let resp = worker
        .call("ping", json!({}), Duration::from_secs(5))
        .await
        .expect("call");
    assert_eq!(resp["pong"], true);
}

#[tokio::test]
async fn bridge_unknown_op_returns_worker_error() {
    let worker = BridgeWorker::spawn(
        "tts_test",
        python_executable(),
        &["-m", "kernel.workers.tts_worker"],
        "..", // tests run from src-tauri/; kernel package lives one up
    )
    .await
    .expect("spawn worker");

    let err = worker
        .call("definitely_not_an_op", json!({}), Duration::from_secs(5))
        .await
        .expect_err("expected worker error");
    let msg = err.to_string();
    assert!(
        msg.contains("ValueError") || msg.contains("unknown op"),
        "unexpected error string: {msg}",
    );
}

#[tokio::test]
async fn bridge_call_after_drop_fails_fast() {
    let worker = BridgeWorker::spawn(
        "tts_test",
        python_executable(),
        &["-m", "kernel.workers.tts_worker"],
        "..", // tests run from src-tauri/; kernel package lives one up
    )
    .await
    .expect("spawn worker");

    // Sanity: ping works.
    let _ = worker
        .call("ping", json!({}), Duration::from_secs(5))
        .await
        .expect("ping");

    // Drop the worker — child gets killed via kill_on_drop.
    drop(worker);
    // Cannot call again — the receiver moved with the drop. This test
    // mainly proves the API doesn't accidentally `Clone` the worker
    // and survive after drop. Compilation alone enforces it; left as a
    // smoke that the test compiles.
}
