//! Silero VAD engine via [`ort`] (ONNX Runtime).
//!
//! Wraps `silero_vad.onnx` (v5 stateful model). API is streaming: feed
//! 32 ms (512 samples at 16 kHz) chunks one at a time, the engine
//! threads the LSTM-style hidden state across calls and returns a
//! per-chunk speech probability in `[0.0, 1.0]`. Call `reset()` between
//! independent utterances so the previous chunk's residual state
//! doesn't bleed into the next.
//!
//! ONNX schema (verified at the bundled model):
//!     inputs:  input (batch, n_samples) f32
//!              state (2, batch, 128)    f32
//!              sr    scalar             i64
//!     outputs: output (batch, 1)        f32   ← speech probability
//!              stateN (2, batch, 128)   f32

use std::path::Path;

use anyhow::{anyhow, Result};
use ndarray::{Array1, Array2, Array3};
use ort::session::builder::GraphOptimizationLevel;
use ort::session::Session;
use ort::value::Tensor;

/// Silero v5 expects exactly 512 samples per chunk at 16 kHz (32 ms).
pub const VAD_CHUNK_SAMPLES: usize = 512;
pub const VAD_SAMPLE_RATE: i64 = 16_000;

pub struct VadEngine {
    session: Session,
    state: Array3<f32>,
}

impl VadEngine {
    pub fn load(model_path: &Path) -> Result<Self> {
        if !model_path.exists() {
            return Err(anyhow!(
                "Silero VAD model not found at {:?}. Download with: \
                 curl -L -o {} https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
                model_path,
                model_path.display(),
            ));
        }
        let session = Session::builder()
            .map_err(|e| anyhow!("ort Session::builder: {e}"))?
            .with_optimization_level(GraphOptimizationLevel::Level3)
            .map_err(|e| anyhow!("set optimization level: {e}"))?
            .commit_from_file(model_path)
            .map_err(|e| anyhow!("load Silero VAD from {:?}: {e}", model_path))?;
        Ok(Self {
            session,
            state: Array3::<f32>::zeros((2, 1, 128)),
        })
    }

    /// Reset hidden state. Call between independent utterances.
    pub fn reset(&mut self) {
        self.state.fill(0.0);
    }

    /// Feed exactly `VAD_CHUNK_SAMPLES` (512) i16 samples at 16 kHz and
    /// return the speech probability in `[0.0, 1.0]`. Updates the
    /// internal hidden state. Mismatched chunk size returns an error
    /// rather than silently padding — caller is responsible for
    /// framing the input stream.
    pub fn feed(&mut self, chunk_i16: &[i16]) -> Result<f32> {
        if chunk_i16.len() != VAD_CHUNK_SAMPLES {
            return Err(anyhow!(
                "Silero VAD expects exactly {} samples per chunk, got {}",
                VAD_CHUNK_SAMPLES,
                chunk_i16.len()
            ));
        }

        let audio: Array2<f32> = Array2::from_shape_fn((1, VAD_CHUNK_SAMPLES), |(_, i)| {
            chunk_i16[i] as f32 / 32768.0
        });
        let sr = Array1::<i64>::from_elem(1, VAD_SAMPLE_RATE);

        let audio_t = Tensor::from_array(audio).map_err(|e| anyhow!("audio tensor: {e}"))?;
        let state_t =
            Tensor::from_array(self.state.clone()).map_err(|e| anyhow!("state tensor: {e}"))?;
        let sr_t = Tensor::from_array(sr).map_err(|e| anyhow!("sr tensor: {e}"))?;

        let outputs = self
            .session
            .run(ort::inputs![
                "input" => audio_t,
                "state" => state_t,
                "sr" => sr_t,
            ])
            .map_err(|e| anyhow!("ort run: {e}"))?;

        let prob_view = outputs["output"]
            .try_extract_array::<f32>()
            .map_err(|e| anyhow!("extract output tensor: {e}"))?;
        let prob = *prob_view
            .iter()
            .next()
            .ok_or_else(|| anyhow!("empty VAD output tensor"))?;

        let state_view = outputs["stateN"]
            .try_extract_array::<f32>()
            .map_err(|e| anyhow!("extract stateN tensor: {e}"))?;
        let new_state =
            Array3::<f32>::from_shape_vec((2, 1, 128), state_view.iter().copied().collect())
                .map_err(|e| anyhow!("reshape stateN: {e}"))?;
        self.state = new_state;

        Ok(prob)
    }
}
