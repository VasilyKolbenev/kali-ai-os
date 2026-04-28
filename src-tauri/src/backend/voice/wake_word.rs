//! Wake-word client over the shared [`BridgeWorker`] (Python sidecar).
//!
//! Phase 3 path B: OpenWakeWord stays in Python. The upstream package
//! orchestrates three ONNX models in sequence (melspectrogram →
//! embedding → keyword classifier); re-implementing that chain in Rust
//! is a parity-risk minefield (mel preprocessing must match within
//! ~5% RMS or false negatives appear). We accept ~5 ms IPC per
//! detection — invisible at the 80 ms wake cadence — for parity
//! certainty and a one-pip-install upgrade path.
//!
//! The Rust client mirrors [`crate::backend::voice::stt::SttClient`]:
//! thin wrapper over an `Arc<BridgeWorker>`. TTS, STT, and wake all
//! share the same Python child process — correlation by id keeps
//! concurrent calls untangled.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::Deserialize;
use serde_json::json;

use crate::backend::voice::bridge::{BridgeError, BridgeWorker};

/// First wake_detect call lazy-loads three ONNX models (~10-20 s cold
/// start). Steady-state inference is well under 100 ms on CPU. Timeout
/// covers cold start; the pipeline must not hammer the worker before
/// the first detection lands.
const WAKE_TIMEOUT: Duration = Duration::from_secs(60);

/// Reset never does heavy work — just clears LSTM state inside the
/// upstream model. A short timeout is fine.
const WAKE_RESET_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Debug, Deserialize)]
struct WakeResultRaw {
    detected: bool,
    word: Option<String>,
    confidence: f32,
}

/// One wake-word detection result. `word` is the matched openwakeword
/// model id (e.g. `"hey_jarvis_v0.1"`) when `detected == true`, else
/// `None`. `confidence` is the highest score across all loaded keyword
/// models, useful for tuning thresholds even on negative results.
#[derive(Debug, Clone)]
pub struct WakeDetection {
    pub detected: bool,
    pub word: Option<String>,
    pub confidence: f32,
}

/// Thin handle over a [`BridgeWorker`]. Cloning is cheap (Arc inside).
#[derive(Clone)]
pub struct WakeWordClient {
    worker: Arc<BridgeWorker>,
}

impl WakeWordClient {
    pub fn new(worker: Arc<BridgeWorker>) -> Self {
        Self { worker }
    }

    /// Run wake-word detection on a 16 kHz mono `i16` PCM buffer.
    /// `threshold` is forwarded to the Python side for thresholding;
    /// callers that want every score (even sub-threshold) can pass
    /// `0.0` and inspect [`WakeDetection::confidence`].
    pub async fn detect(
        &self,
        samples_i16: &[i16],
        sample_rate: u32,
        threshold: f32,
    ) -> Result<WakeDetection> {
        let bytes: Vec<u8> = samples_i16
            .iter()
            .flat_map(|s| s.to_le_bytes())
            .collect();
        let audio_b64 = STANDARD.encode(&bytes);
        let args = json!({
            "audio_b64": audio_b64,
            "sample_rate": sample_rate,
            "threshold": threshold,
        });

        let value = self
            .worker
            .call("wake_detect", args, WAKE_TIMEOUT)
            .await
            .map_err(|err: BridgeError| anyhow!("wake_word worker: {err}"))?;
        let parsed: WakeResultRaw =
            serde_json::from_value(value).context("decode wake_detect result envelope")?;
        Ok(WakeDetection {
            detected: parsed.detected,
            word: parsed.word,
            confidence: parsed.confidence,
        })
    }

    /// Clear the model's hidden state between independent utterances.
    /// Call when the pipeline transitions out of capture so residual
    /// context from the previous wake doesn't bleed into the next.
    pub async fn reset(&self) -> Result<()> {
        self.worker
            .call("wake_reset", json!({}), WAKE_RESET_TIMEOUT)
            .await
            .map_err(|err: BridgeError| anyhow!("wake_word reset: {err}"))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Mirror of the STT/TTS round-trip — proves audio_b64 wire format
    /// is endianness-correct without needing a live worker. Rust
    /// encodes i16 LE → base64; Python will decode exactly the same.
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
