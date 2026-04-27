//! Silero VAD live test — gated behind `--features ml-tests`.
//!
//! What this validates:
//!   - The bundled `models/silero_vad.onnx` loads via `ort` 2.x without
//!     CUDA / GPU dependencies (CPU EP is enough for VAD's tiny model).
//!   - The `feed()` API consumes 32 ms / 512-sample chunks at 16 kHz
//!     and returns probabilities in `[0, 1]`.
//!   - On 1 s of pure silence, no chunk crosses the 0.2 floor.
//!
//! What this DOES NOT validate (intentionally):
//!   - VAD activation on synthetic F5-TTS audio. F5 24 kHz output run
//!     through a naive 3:2 decimation (no anti-alias) ends up with
//!     enough high-frequency aliasing that Silero classifies it as
//!     silence. The same issue bites Whisper STT on the same path.
//!     Production input is 16 kHz native from `cpal`, so the
//!     decimation step doesn't exist on the real path. A proper
//!     activation test arrives in Chunk 7 once the recorder is in
//!     place; an `#[ignore]`'d stub below keeps the intent visible.
//!
//! Run on demand:
//!     cargo test --test voice_vad --features ml-tests --release

#![cfg(feature = "ml-tests")]

use std::path::Path;

use kali_desktop::backend::voice::vad::{VadEngine, VAD_CHUNK_SAMPLES};

fn vad_model_path() -> &'static Path {
    Path::new("../models/silero_vad.onnx")
}

#[tokio::test]
async fn vad_classifies_silence_below_threshold() {
    let mut vad = VadEngine::load(vad_model_path()).expect("load VAD");
    let silence = vec![0i16; 16_000]; // 1 s at 16 kHz

    let mut max_prob = 0.0f32;
    for chunk in silence.chunks_exact(VAD_CHUNK_SAMPLES) {
        let p = vad.feed(chunk).expect("feed silence");
        max_prob = max_prob.max(p);
    }
    println!("VAD silence max_prob = {max_prob:.4}");
    assert!(
        max_prob < 0.2,
        "VAD should not fire on 1s of pure silence; saw max prob {max_prob}",
    );
}

#[tokio::test]
async fn vad_chunk_size_mismatch_errors() {
    let mut vad = VadEngine::load(vad_model_path()).expect("load VAD");
    let too_small = vec![0i16; 256];
    let err = vad.feed(&too_small).expect_err("expected size error");
    let msg = err.to_string();
    assert!(
        msg.contains("expects exactly"),
        "unexpected error: {msg}",
    );
}

#[tokio::test]
async fn vad_reset_zeros_state() {
    let mut vad = VadEngine::load(vad_model_path()).expect("load VAD");
    // Drive VAD with random-ish noise so its hidden state ends up non-zero.
    let mut chunk = [0i16; VAD_CHUNK_SAMPLES];
    for (i, s) in chunk.iter_mut().enumerate() {
        *s = ((i as i32 * 37) % 4096) as i16;
    }
    for _ in 0..5 {
        vad.feed(&chunk).expect("feed");
    }
    vad.reset();
    // After reset, silence chunks must again read as silent — proves the
    // state was actually cleared (residual hidden state would inflate
    // probabilities for several chunks post-reset).
    let silence = [0i16; VAD_CHUNK_SAMPLES];
    let p = vad.feed(&silence).expect("feed post-reset");
    assert!(p < 0.2, "post-reset silence should be silent; got {p}");
}

#[tokio::test]
#[ignore = "naive 3:2 decimation of F5 output aliases below Silero's threshold; \
            real activation test deferred to Chunk 7 with a 16kHz cpal source"]
async fn vad_activates_on_speech_via_decimated_f5() {
    // Stub kept for documentation. See module-level comment for why.
}
