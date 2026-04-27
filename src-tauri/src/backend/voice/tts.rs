//! TTS client over [`BridgeWorker`].
//!
//! Phase 3 Chunk 2 — sends a `tts_speak` op to the Python worker and
//! decodes the base64 f32 little-endian waveform back into a Vec<f32>.
//! Subsequent chunks (recorder/playback) consume `Speech` directly.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::Deserialize;
use serde_json::json;

use crate::backend::voice::bridge::{BridgeError, BridgeWorker};

/// First call lazy-loads F5-TTS (~30-60s on warm GPU). Steady-state
/// inference is ~500ms-2s for 1-3s of speech. The timeout covers cold
/// start; the pipeline must not hammer the worker before the first
/// reply lands.
const TTS_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Debug, Deserialize)]
struct TtsResult {
    audio_b64: String,
    sample_rate: u32,
    duration_ms: u32,
}

/// Synthesised speech: raw f32 PCM samples plus their sample rate.
#[derive(Debug, Clone)]
pub struct Speech {
    pub samples: Vec<f32>,
    pub sample_rate: u32,
    pub duration_ms: u32,
}

/// Thin handle over a [`BridgeWorker`]. Cloning is cheap (Arc inside).
#[derive(Clone)]
pub struct TtsClient {
    worker: Arc<BridgeWorker>,
}

impl TtsClient {
    pub fn new(worker: Arc<BridgeWorker>) -> Self {
        Self { worker }
    }

    pub async fn speak(&self, text: &str) -> Result<Speech> {
        let value = self
            .worker
            .call("tts_speak", json!({ "text": text }), TTS_TIMEOUT)
            .await
            .map_err(|err: BridgeError| anyhow!("tts worker: {err}"))?;
        let parsed: TtsResult =
            serde_json::from_value(value).context("decode tts_speak result envelope")?;
        let bytes = STANDARD
            .decode(parsed.audio_b64.as_bytes())
            .context("decode audio_b64")?;
        if !bytes.len().is_multiple_of(4) {
            return Err(anyhow!(
                "audio_b64 length {} not divisible by 4 (expected f32 LE)",
                bytes.len()
            ));
        }
        let samples: Vec<f32> = bytes
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        Ok(Speech {
            samples,
            sample_rate: parsed.sample_rate,
            duration_ms: parsed.duration_ms,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Round-trip a known f32 sequence through the same base64 encoding
    /// the Python worker uses, then through `Speech` decoding. Catches
    /// endianness or chunk-boundary bugs without needing a live worker.
    #[test]
    fn decode_round_trip_preserves_samples() {
        let original: Vec<f32> = (0..16).map(|i| i as f32 * 0.1 - 0.5).collect();
        let bytes: Vec<u8> = original
            .iter()
            .flat_map(|s| s.to_le_bytes())
            .collect();
        let b64 = STANDARD.encode(&bytes);

        // Decode the way TtsClient::speak does.
        let decoded_bytes = STANDARD.decode(b64.as_bytes()).unwrap();
        assert_eq!(decoded_bytes.len(), original.len() * 4);
        let recovered: Vec<f32> = decoded_bytes
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        assert_eq!(recovered, original);
    }
}
