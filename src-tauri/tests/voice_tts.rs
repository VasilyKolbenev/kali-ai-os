//! Live TTS test — gated behind `--features ml-tests` because it
//! lazy-loads F5-TTS on first call (~60s warm-up on a cold GPU). Skip
//! by default; run on demand with:
//!     cargo test --test voice_tts --features ml-tests
//! Requires a working CUDA setup, the F5 model files in `models/`, and
//! the FFmpeg DLLs the Python engine pulls in.

#![cfg(feature = "ml-tests")]

use std::sync::Arc;
use std::time::Duration;

use kali_desktop::backend::voice::{bridge::BridgeWorker, tts::TtsClient};

fn python_executable() -> String {
    std::env::var("KALI_PY").unwrap_or_else(|_| "../.venv/Scripts/python.exe".to_string())
}

#[tokio::test]
async fn tts_speak_returns_nonempty_waveform() {
    let worker = BridgeWorker::spawn(
        "tts",
        python_executable(),
        &["-m", "kernel.workers.tts_worker"],
        "..",
    )
    .await
    .expect("spawn worker");
    let client = TtsClient::new(Arc::new(worker));

    let speech = tokio::time::timeout(Duration::from_secs(180), client.speak("Тест синтеза."))
        .await
        .expect("speak deadline")
        .expect("speak ok");

    // 24kHz × ≥ 250ms ⇒ ≥ 6000 samples. F5 typically gives ~1-3s for short Russian.
    assert!(
        speech.samples.len() >= 6000,
        "waveform too short: {} samples",
        speech.samples.len(),
    );
    assert_eq!(speech.sample_rate, 24000);
    assert!(speech.duration_ms >= 250);
}
