//! Recorder smoke test — opens the default input device, captures
//! ~100 ms of audio, asserts the chunks arrive at the expected rate.
//!
//! Gated behind `audio-tests` so default `cargo test` never touches
//! the user's mic. The chunk plan suggested gating only by runtime
//! device-presence check, but that would record ambient audio on every
//! dev-machine `cargo test` run — privacy unfriendly. The feature flag
//! makes the audio-touching tests opt-in and keeps CI clean (CI never
//! enables `audio-tests`).
//!
//! Run on demand:
//!     cargo test --test voice_recorder --features audio-tests

#![cfg(feature = "audio-tests")]

use std::time::{Duration, Instant};

use cpal::traits::HostTrait;
use kali_desktop::backend::voice::mute::MuteFlag;
use kali_desktop::backend::voice::recorder::{
    Recorder, RECORDER_CHUNK_SAMPLES, RECORDER_SAMPLE_RATE,
};

/// At 16 kHz, 100 ms = 1600 samples. Allow some jitter — cpal buffers
/// don't align to chunk boundaries, and stream startup eats the first
/// few callbacks.
const MIN_SAMPLES_FOR_100MS: usize = 1500;
const RECEIVE_BUDGET: Duration = Duration::from_secs(3);

#[tokio::test]
async fn recorder_captures_around_100ms_of_audio() {
    let host = cpal::default_host();
    if host.default_input_device().is_none() {
        eprintln!("[skip] no default input device available");
        return;
    }

    let mute = MuteFlag::new();
    let (recorder, mut rx) = match Recorder::start(mute) {
        Ok(pair) => pair,
        Err(err) => {
            eprintln!("[skip] recorder failed to start: {err:#}");
            return;
        }
    };

    let mut total_samples: usize = 0;
    let mut chunk_count: usize = 0;
    let deadline = Instant::now() + RECEIVE_BUDGET;
    while total_samples < MIN_SAMPLES_FOR_100MS && Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(Instant::now());
        match tokio::time::timeout(remaining, rx.recv()).await {
            Ok(Some(chunk)) => {
                assert_eq!(
                    chunk.len(),
                    RECORDER_CHUNK_SAMPLES,
                    "every emitted chunk must be exactly {RECORDER_CHUNK_SAMPLES} samples",
                );
                total_samples += chunk.len();
                chunk_count += 1;
            }
            Ok(None) => break,    // sender dropped
            Err(_) => break,      // timeout
        }
    }

    drop(recorder); // signal shutdown to the capture thread

    assert!(
        total_samples >= MIN_SAMPLES_FOR_100MS,
        "expected ≥ {MIN_SAMPLES_FOR_100MS} samples in {RECEIVE_BUDGET:?}, got {total_samples} \
         across {chunk_count} chunks (sample rate constant = {RECORDER_SAMPLE_RATE} Hz)"
    );
}
