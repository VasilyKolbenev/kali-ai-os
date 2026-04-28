//! Wake-word E2E (path B: Python sidecar via the JSON-stdio bridge).
//!
//! Same approach as STT Chunk 3 — keep the model in Python rather than
//! re-implementing OpenWakeWord's three-ONNX preprocessing chain
//! (melspectrogram → embedding → keyword) on the Rust side. The
//! upstream `openwakeword` package owns the chain; we just expose it
//! over the bridge.
//!
//! What this validates:
//!   1. Worker accepts `wake_detect` op + `wake_reset` op.
//!   2. 1 s of pure silence does NOT trigger a positive detection
//!      (confidence floor < 0.1) — proves the protocol round-trip
//!      AND that the model isn't stuck firing constantly.
//!   3. `wake_reset` returns `ok: true` (state machine wiring in
//!      Chunk 7 will need this between utterances).
//!
//! What this DOES NOT validate (intentionally):
//!   - True-positive activation on a real "hey jarvis" utterance.
//!     We don't have a clean fixture in the repo yet; recording one
//!     belongs to Chunk 7 when the cpal recorder is wired into the
//!     pipeline. Until then, accuracy is taken on the openwakeword
//!     project's reputation (and the live tests Vasily will run at
//!     the end of Phase 3).
//!
//! Run on demand:
//!     cargo test --test voice_wake_word --features ml-tests --release

#![cfg(feature = "ml-tests")]

use std::sync::Arc;
use std::time::Duration;

use kali_desktop::backend::voice::{bridge::BridgeWorker, wake_word::WakeWordClient};

fn python_executable() -> String {
    std::env::var("KALI_PY").unwrap_or_else(|_| "../.venv/Scripts/python.exe".to_string())
}

#[tokio::test]
async fn wake_word_does_not_fire_on_silence() {
    let worker = Arc::new(
        BridgeWorker::spawn(
            "ml",
            python_executable(),
            &["-m", "kernel.workers.tts_worker"],
            "..",
        )
        .await
        .expect("spawn worker"),
    );
    let wake = WakeWordClient::new(worker.clone());

    // 1 s of silence at 16 kHz = 16000 samples. OpenWakeWord's minimum
    // is 1280 samples (80 ms); 1 s gives the model plenty of context
    // and exercises the multi-window code path inside the upstream
    // package without us having to know the exact chunking.
    let silence = vec![0i16; 16_000];

    // First call lazy-loads three ONNX models (melspectrogram +
    // embedding + hey_jarvis_v0.1). Cold-start budget ~15-20 s on a
    // dev box; allow 60 s to keep CI / first-run friendly.
    let detection = tokio::time::timeout(
        Duration::from_secs(60),
        wake.detect(&silence, 16_000, 0.5),
    )
    .await
    .expect("wake_detect deadline")
    .expect("wake_detect ok");

    println!(
        "wake silence result: detected={} word={:?} confidence={:.4}",
        detection.detected, detection.word, detection.confidence,
    );
    assert!(
        !detection.detected,
        "1 s of pure silence must not fire wake word (got word={:?}, conf={})",
        detection.word, detection.confidence,
    );
    assert!(
        detection.confidence < 0.1,
        "silence confidence floor should stay < 0.1, got {}",
        detection.confidence,
    );
}

#[tokio::test]
async fn wake_reset_returns_ok() {
    let worker = Arc::new(
        BridgeWorker::spawn(
            "ml",
            python_executable(),
            &["-m", "kernel.workers.tts_worker"],
            "..",
        )
        .await
        .expect("spawn worker"),
    );
    let wake = WakeWordClient::new(worker.clone());

    // Reset before any detect call — must succeed even when the model
    // hasn't been lazy-loaded yet (Python side initialises on demand).
    tokio::time::timeout(Duration::from_secs(30), wake.reset())
        .await
        .expect("wake_reset deadline")
        .expect("wake_reset ok");
}
