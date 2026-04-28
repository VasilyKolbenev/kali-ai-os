//! Microphone capture via [`cpal`] — 16 kHz mono i16 chunks of 30 ms
//! (480 samples). Output is a [`tokio::sync::mpsc::Receiver<Vec<i16>>`]
//! consumed by the pipeline state machine (Chunk 7).
//!
//! ## Threading
//!
//! `cpal::Stream` is `!Send` on some hosts (CoreAudio in particular) so
//! we can't keep it on a tokio task. The recorder owns a dedicated
//! `std::thread` which builds and plays the stream, then blocks on a
//! shutdown signal. `Recorder` itself is `Send` — pipeline can carry it
//! across executors freely.
//!
//! ## Anti-echo mute
//!
//! When the shared [`MuteFlag`] is set, completed chunks are zeroed
//! before being sent. This keeps the consumer's clock steady (one chunk
//! per 30 ms regardless of mute state) so the state machine doesn't
//! need to special-case "speaking" vs "listening" timing.

use std::sync::mpsc as std_mpsc;
use std::thread;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{SampleFormat, StreamConfig};
use tokio::sync::mpsc as tokio_mpsc;
use tracing::{error, info, warn};

use crate::backend::voice::mute::MuteFlag;

/// Target sample rate. VAD, wake word, and STT all expect 16 kHz; recording
/// natively at this rate avoids the resampling-aliasing trap from Phase 3
/// Chunk 4 (see `memory/feedback_ml_build_friction.md` rule 6).
pub const RECORDER_SAMPLE_RATE: u32 = 16_000;

/// 30 ms at 16 kHz. Compatible with VAD's 32 ms / 512-sample window after
/// minor re-framing in the state machine; the pipeline owns the framing.
pub const RECORDER_CHUNK_SAMPLES: usize = 480;

/// Bounded channel between the cpal callback and the async consumer. 64
/// chunks ≈ 1.9 s of audio buffered. Drops with a warn if the consumer
/// stalls — guards against unbounded memory growth on a stuck pipeline.
const AUDIO_CHANNEL_CAPACITY: usize = 64;

/// Push `incoming` samples into `accumulator`. Whenever the accumulator
/// reaches `chunk_size`, drain a chunk and call `emit`. Pure function —
/// no I/O, no globals — so the cpal callback's framing logic stays
/// unit-testable.
pub(crate) fn accumulate_into_chunks<F: FnMut(Vec<i16>)>(
    accumulator: &mut Vec<i16>,
    incoming: &[i16],
    chunk_size: usize,
    mut emit: F,
) {
    accumulator.extend_from_slice(incoming);
    while accumulator.len() >= chunk_size {
        let chunk: Vec<i16> = accumulator.drain(..chunk_size).collect();
        emit(chunk);
    }
}

/// Apply mute: if the flag is set, return a zeroed chunk of the same
/// length; otherwise return the chunk unchanged. Zeroing rather than
/// dropping preserves the consumer's clock — one chunk per 30 ms either
/// way.
pub(crate) fn apply_mute(chunk: Vec<i16>, mute: &MuteFlag) -> Vec<i16> {
    if mute.is_muted() {
        vec![0; chunk.len()]
    } else {
        chunk
    }
}

/// Handle to a running cpal capture stream. Drop to stop recording.
pub struct Recorder {
    shutdown: Option<std_mpsc::Sender<()>>,
    thread: Option<thread::JoinHandle<()>>,
}

impl Drop for Recorder {
    fn drop(&mut self) {
        // Dropping the shutdown sender wakes the worker thread's
        // `recv()` with `Err` — that's the cue to drop the cpal stream
        // and exit cleanly.
        self.shutdown.take();
        if let Some(handle) = self.thread.take() {
            // Best-effort join; thread should exit within ~10 ms once
            // the shutdown channel closes.
            let _ = handle.join();
        }
    }
}

impl Recorder {
    /// Start capture on the default input device. Returns the recorder
    /// handle plus an async receiver of 30 ms chunks. Drop the handle
    /// to stop.
    pub fn start(mute: MuteFlag) -> Result<(Self, tokio_mpsc::Receiver<Vec<i16>>)> {
        let (audio_tx, audio_rx) = tokio_mpsc::channel(AUDIO_CHANNEL_CAPACITY);
        let (init_tx, init_rx) = std_mpsc::channel::<Result<()>>();
        let (shutdown_tx, shutdown_rx) = std_mpsc::channel::<()>();

        let thread = thread::Builder::new()
            .name("kali-recorder".into())
            .spawn(move || run_capture_thread(audio_tx, mute, init_tx, shutdown_rx))
            .context("spawn recorder thread")?;

        // Wait for the worker to either succeed or fail to build the
        // stream. Without this, callers couldn't distinguish "device
        // missing" from "no audio yet".
        match init_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(Ok(())) => Ok((
                Self {
                    shutdown: Some(shutdown_tx),
                    thread: Some(thread),
                },
                audio_rx,
            )),
            Ok(Err(err)) => Err(err),
            Err(_) => Err(anyhow!("recorder thread did not initialise within 5 s")),
        }
    }
}

/// Run the cpal capture stream on a dedicated OS thread. The closure
/// pattern matches what cpal expects (`build_input_stream(_, _, _, _)`).
/// Stream lives until `shutdown_rx` returns Err (the sender was dropped).
fn run_capture_thread(
    audio_tx: tokio_mpsc::Sender<Vec<i16>>,
    mute: MuteFlag,
    init_tx: std_mpsc::Sender<Result<()>>,
    shutdown_rx: std_mpsc::Receiver<()>,
) {
    let stream = match build_input_stream(audio_tx, mute) {
        Ok(s) => s,
        Err(err) => {
            // Caller is waiting on init_rx; send the error and exit.
            let _ = init_tx.send(Err(err));
            return;
        }
    };

    if let Err(err) = stream.play() {
        let _ = init_tx.send(Err(anyhow!("cpal stream.play(): {err}")));
        return;
    }

    info!(
        sample_rate = RECORDER_SAMPLE_RATE,
        chunk_samples = RECORDER_CHUNK_SAMPLES,
        "recorder stream playing"
    );
    let _ = init_tx.send(Ok(()));

    // Block until the shutdown sender is dropped. Returns Err on close,
    // which is the signal we want — drop the stream below and exit.
    let _ = shutdown_rx.recv();
    drop(stream);
    info!("recorder stream stopped");
}

fn build_input_stream(
    audio_tx: tokio_mpsc::Sender<Vec<i16>>,
    mute: MuteFlag,
) -> Result<cpal::Stream> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or_else(|| anyhow!("no default input device available"))?;
    // cpal 0.17 deprecated `.name()` in favour of `.description()` /
    // `.id()` but the new API surface is not yet stabilised for our
    // logging needs. Keep `.name()` and revisit during the cpal-bump
    // polish pass after Phase 3.
    #[allow(deprecated)]
    let device_name = device.name().unwrap_or_else(|_| "<unnamed>".into());
    info!(device = %device_name, "recorder using input device");

    let config = StreamConfig {
        channels: 1,
        sample_rate: RECORDER_SAMPLE_RATE,
        buffer_size: cpal::BufferSize::Default,
    };

    // Probe supported formats: prefer i16 native to skip an in-callback
    // conversion. Most Windows WASAPI shared-mode devices return f32 —
    // we handle that case below. cpal 0.17 returns sample rates as
    // primitive u32 (was tuple struct in 0.16).
    let supported = device
        .supported_input_configs()
        .context("query supported input configs")?
        .find(|c| {
            c.channels() == 1
                && c.min_sample_rate() <= RECORDER_SAMPLE_RATE
                && c.max_sample_rate() >= RECORDER_SAMPLE_RATE
        })
        .ok_or_else(|| {
            anyhow!(
                "input device {} does not support 16 kHz mono",
                device_name
            )
        })?;
    let sample_format = supported.sample_format();

    let mut acc: Vec<i16> = Vec::with_capacity(RECORDER_CHUNK_SAMPLES * 2);
    let err_fn = |err: cpal::StreamError| error!(?err, "cpal input stream error");

    let stream = match sample_format {
        SampleFormat::I16 => device
            .build_input_stream(
                &config,
                move |data: &[i16], _| dispatch(data, &mut acc, &mute, &audio_tx),
                err_fn,
                None,
            )
            .context("build i16 input stream")?,
        SampleFormat::F32 => device
            .build_input_stream(
                &config,
                move |data: &[f32], _| {
                    let i16_buf: Vec<i16> = data.iter().map(f32_to_i16).collect();
                    dispatch(&i16_buf, &mut acc, &mute, &audio_tx);
                },
                err_fn,
                None,
            )
            .context("build f32 input stream")?,
        other => return Err(anyhow!("unsupported sample format: {other:?}")),
    };

    Ok(stream)
}

fn dispatch(
    data: &[i16],
    acc: &mut Vec<i16>,
    mute: &MuteFlag,
    audio_tx: &tokio_mpsc::Sender<Vec<i16>>,
) {
    accumulate_into_chunks(acc, data, RECORDER_CHUNK_SAMPLES, |chunk| {
        let out = apply_mute(chunk, mute);
        if let Err(err) = audio_tx.try_send(out) {
            warn!(?err, "recorder dropped chunk: consumer not draining");
        }
    });
}

#[inline]
fn f32_to_i16(s: &f32) -> i16 {
    let clamped = s.clamp(-1.0, 1.0);
    (clamped * i16::MAX as f32) as i16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accumulate_empty_input_yields_no_chunks() {
        let mut acc = Vec::new();
        let mut emitted: Vec<Vec<i16>> = Vec::new();
        accumulate_into_chunks(&mut acc, &[], 4, |c| emitted.push(c));
        assert!(emitted.is_empty());
        assert!(acc.is_empty());
    }

    #[test]
    fn accumulate_partial_input_keeps_in_buffer() {
        let mut acc = Vec::new();
        let mut emitted: Vec<Vec<i16>> = Vec::new();
        accumulate_into_chunks(&mut acc, &[1, 2, 3], 4, |c| emitted.push(c));
        assert!(emitted.is_empty());
        assert_eq!(acc, vec![1, 2, 3]);
    }

    #[test]
    fn accumulate_emits_one_full_chunk() {
        let mut acc = Vec::new();
        let mut emitted: Vec<Vec<i16>> = Vec::new();
        accumulate_into_chunks(&mut acc, &[1, 2, 3, 4], 4, |c| emitted.push(c));
        assert_eq!(emitted, vec![vec![1, 2, 3, 4]]);
        assert!(acc.is_empty());
    }

    #[test]
    fn accumulate_emits_multiple_and_keeps_remainder() {
        let mut acc = vec![100i16];
        let mut emitted: Vec<Vec<i16>> = Vec::new();
        accumulate_into_chunks(&mut acc, &[1, 2, 3, 4, 5, 6, 7, 8], 4, |c| {
            emitted.push(c)
        });
        assert_eq!(emitted, vec![vec![100, 1, 2, 3], vec![4, 5, 6, 7]]);
        assert_eq!(acc, vec![8]);
    }

    #[test]
    fn apply_mute_when_unmuted_returns_input_unchanged() {
        let flag = MuteFlag::new();
        let result = apply_mute(vec![1, 2, 3, 4], &flag);
        assert_eq!(result, vec![1, 2, 3, 4]);
    }

    #[test]
    fn apply_mute_when_muted_returns_zeros_of_same_length() {
        let flag = MuteFlag::new();
        flag.set_muted(true);
        let result = apply_mute(vec![1, 2, 3, 4], &flag);
        assert_eq!(result, vec![0, 0, 0, 0]);
    }

    #[test]
    fn apply_mute_preserves_empty_input() {
        let flag = MuteFlag::new();
        flag.set_muted(true);
        let result = apply_mute(Vec::new(), &flag);
        assert!(result.is_empty());
    }

    #[test]
    fn f32_to_i16_clips_at_extremes() {
        assert_eq!(f32_to_i16(&-2.0), -i16::MAX); // -1.0 * 32767 → -32767
        assert_eq!(f32_to_i16(&2.0), i16::MAX);
        assert_eq!(f32_to_i16(&0.0), 0);
    }
}
