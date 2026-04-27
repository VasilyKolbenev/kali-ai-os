//! STT client over the shared [`BridgeWorker`] (Python sidecar).
//!
//! Phase 3 path B: Whisper STT stays in Python via `faster_whisper`.
//! Rationale: `whisper-rs` 0.16 on Windows requires LLVM + CMake +
//! Ninja + a full Visual Studio IDE installation just to compile the
//! whisper.cpp C++ bindings. `faster_whisper` (Python, CTranslate2
//! backend) is mature, ~5x faster than reference Whisper, and already
//! co-located with F5-TTS + ruaccent in the worker we built in
//! Chunk 2 — adding a `stt_transcribe` op is a one-file change on the
//! Python side. We can revisit a Rust-native STT path in a later phase
//! if `whisper-rs` build deps stabilise on Windows or an alternative
//! crate (`whisper_burn`) reaches production maturity.
//!
//! The Rust client mirrors [`TtsClient`]: thin wrapper over an
//! `Arc<BridgeWorker>`. TTS and STT clients share the same underlying
//! worker — one Python child process serves both, correlation by id
//! keeps concurrent calls untangled.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::Deserialize;
use serde_json::json;

use crate::backend::voice::bridge::{BridgeError, BridgeWorker};

/// First STT call lazy-loads the Whisper model (~3-5s for `base`).
/// Steady-state inference is fast (CTranslate2 base on RTX): typically
/// 0.1-0.3x realtime, so a 5s utterance transcribes in 0.5-1.5s. The
/// timeout covers cold start; the pipeline must not hammer the worker
/// before the first reply lands.
const STT_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Debug, Deserialize)]
struct SttResult {
    text: String,
    language: Option<String>,
    duration_ms: Option<u32>,
}

/// A transcribed utterance. `language` is whatever Whisper detected
/// (or the explicit hint you passed in `transcribe`); `duration_ms` is
/// the audio length the worker actually processed, useful for logging
/// realtime factors.
#[derive(Debug, Clone)]
pub struct Transcript {
    pub text: String,
    pub language: Option<String>,
    pub duration_ms: Option<u32>,
}

/// Thin handle over a [`BridgeWorker`]. Cloning is cheap (Arc inside).
#[derive(Clone)]
pub struct SttClient {
    worker: Arc<BridgeWorker>,
}

impl SttClient {
    pub fn new(worker: Arc<BridgeWorker>) -> Self {
        Self { worker }
    }

    /// Transcribe a 16 kHz mono `i16` PCM buffer. `language_hint` is an
    /// optional ISO 639-1 code (e.g. "ru", "en") — pass `None` to let
    /// Whisper detect. Returns the trimmed transcript text plus the
    /// detected language.
    pub async fn transcribe(
        &self,
        samples_i16: &[i16],
        sample_rate: u32,
        language_hint: Option<&str>,
    ) -> Result<Transcript> {
        let bytes: Vec<u8> = samples_i16
            .iter()
            .flat_map(|s| s.to_le_bytes())
            .collect();
        let audio_b64 = STANDARD.encode(&bytes);
        let mut args = json!({
            "audio_b64": audio_b64,
            "sample_rate": sample_rate,
        });
        if let Some(lang) = language_hint {
            args["language"] = json!(lang);
        }

        let value = self
            .worker
            .call("stt_transcribe", args, STT_TIMEOUT)
            .await
            .map_err(|err: BridgeError| anyhow!("stt worker: {err}"))?;
        let parsed: SttResult =
            serde_json::from_value(value).context("decode stt_transcribe result envelope")?;
        Ok(Transcript {
            text: parsed.text,
            language: parsed.language,
            duration_ms: parsed.duration_ms,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Encode/decode round-trip on a known i16 sequence — same base64
    /// pair the Python worker uses to receive audio. Catches endianness
    /// or chunk-size bugs without needing a live worker.
    #[test]
    fn audio_b64_round_trip_preserves_samples() {
        let original: Vec<i16> = (-8..8).map(|i| i * 1024).collect();
        let bytes: Vec<u8> = original.iter().flat_map(|s| s.to_le_bytes()).collect();
        let b64 = STANDARD.encode(&bytes);

        let decoded = STANDARD.decode(b64.as_bytes()).unwrap();
        assert_eq!(decoded.len(), original.len() * 2);
        let recovered: Vec<i16> = decoded
            .chunks_exact(2)
            .map(|c| i16::from_le_bytes([c[0], c[1]]))
            .collect();
        assert_eq!(recovered, original);
    }
}
