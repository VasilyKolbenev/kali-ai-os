//! Microphone capture via [`cpal`] — 16 kHz mono i16 chunks of 30 ms
//! (480 samples). Output is a [`tokio::sync::mpsc::Receiver<Vec<i16>>`]
//! consumed by the pipeline state machine (Chunk 7).
//!
//! ## Capture format & resampling
//!
//! VAD, wake word, and STT all expect 16 kHz mono. Many real input
//! devices — laptop mic arrays on Windows/WASAPI especially — do NOT
//! expose a 16 kHz mono config; they report only their native mix
//! format (e.g. 48 kHz, 1-2 channels). So we:
//!   1. Prefer an exact 16 kHz mono config when the device offers one —
//!      zero-cost, no resampling (the original Phase 3 happy path).
//!   2. Otherwise capture at the device's default config and convert in
//!      the callback: downmix to mono, then resample to 16 kHz with an
//!      anti-aliased FFT resampler ([`rubato`]). This is NOT naive
//!      decimation — naive decimation aliases (Phase 3 Chunk 4 lesson,
//!      `memory/feedback_ml_build_friction.md` rule 6).
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
use rubato::{FftFixedIn, Resampler};
use tokio::sync::mpsc as tokio_mpsc;
use tracing::{error, info, warn};

use crate::backend::voice::mute::MuteFlag;

/// Target sample rate. VAD, wake word, and STT all expect 16 kHz.
pub const RECORDER_SAMPLE_RATE: u32 = 16_000;

/// 30 ms at 16 kHz. Compatible with VAD's 32 ms / 512-sample window after
/// minor re-framing in the state machine; the pipeline owns the framing.
pub const RECORDER_CHUNK_SAMPLES: usize = 480;

/// Bounded channel between the cpal callback and the async consumer. 64
/// chunks ≈ 1.9 s of audio buffered. Drops with a warn if the consumer
/// stalls — guards against unbounded memory growth on a stuck pipeline.
const AUDIO_CHANNEL_CAPACITY: usize = 64;

/// Input block size (native-rate frames) fed to the FFT resampler per
/// step. The resampler reports its exact required size via
/// `input_frames_next()`; this is the construction hint.
const RESAMPLER_BLOCK: usize = 1024;

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

/// Average interleaved multi-channel samples into a mono stream. A
/// `channels <= 1` input is returned as a plain copy. Pure —
/// unit-tested.
pub(crate) fn downmix_to_mono_f32(interleaved: &[f32], channels: usize) -> Vec<f32> {
    if channels <= 1 {
        return interleaved.to_vec();
    }
    let frames = interleaved.len() / channels;
    let mut out = Vec::with_capacity(frames);
    for f in 0..frames {
        let base = f * channels;
        let sum: f32 = interleaved[base..base + channels].iter().sum();
        out.push(sum / channels as f32);
    }
    out
}

#[inline]
pub(crate) fn i16_to_f32(s: i16) -> f32 {
    s as f32 / i16::MAX as f32
}

#[inline]
pub(crate) fn f32_to_i16(s: f32) -> i16 {
    let clamped = s.clamp(-1.0, 1.0);
    (clamped * i16::MAX as f32) as i16
}

/// Streaming sample-rate converter: arbitrary native rate (mono f32) →
/// 16 kHz mono f32, anti-aliased via rubato's FFT resampler. Buffers
/// incoming samples and feeds the resampler its required fixed-size
/// input blocks, returning whatever 16 kHz output is produced so far.
struct Resampler16k {
    inner: FftFixedIn<f32>,
    in_buf: Vec<f32>,
}

impl Resampler16k {
    fn new(native_rate: u32) -> Result<Self> {
        let inner = FftFixedIn::<f32>::new(
            native_rate as usize,
            RECORDER_SAMPLE_RATE as usize,
            RESAMPLER_BLOCK,
            2, // sub-chunks
            1, // mono
        )
        .context("init FFT resampler")?;
        Ok(Self {
            inner,
            in_buf: Vec::with_capacity(RESAMPLER_BLOCK * 2),
        })
    }

    /// Push native-rate mono samples; return any 16 kHz output produced.
    fn push(&mut self, samples: &[f32]) -> Vec<f32> {
        self.in_buf.extend_from_slice(samples);
        let mut out = Vec::new();
        loop {
            let need = self.inner.input_frames_next();
            if self.in_buf.len() < need {
                break;
            }
            let chunk: Vec<f32> = self.in_buf.drain(..need).collect();
            match self.inner.process(&[chunk], None) {
                Ok(mut res) => {
                    if let Some(ch0) = res.drain(..).next() {
                        out.extend_from_slice(&ch0);
                    }
                }
                Err(err) => {
                    warn!(?err, "resampler process error; dropping block");
                    break;
                }
            }
        }
        out
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

    // ── Fast path: device offers exact 16 kHz mono — capture directly,
    // no resampling (the original Phase 3 happy path). cpal 0.17 returns
    // sample rates as primitive u32 (was a tuple struct in 0.16).
    let direct = device
        .supported_input_configs()
        .context("query supported input configs")?
        .find(|c| {
            c.channels() == 1
                && c.min_sample_rate() <= RECORDER_SAMPLE_RATE
                && c.max_sample_rate() >= RECORDER_SAMPLE_RATE
        });

    if let Some(supported) = direct {
        let sample_format = supported.sample_format();
        let config = StreamConfig {
            channels: 1,
            sample_rate: RECORDER_SAMPLE_RATE,
            buffer_size: cpal::BufferSize::Default,
        };
        info!(?sample_format, mode = "direct-16k-mono", "recorder capture config");
        let mut acc: Vec<i16> = Vec::with_capacity(RECORDER_CHUNK_SAMPLES * 2);
        let stream = match sample_format {
            SampleFormat::I16 => device
                .build_input_stream(
                    &config,
                    move |data: &[i16], _| dispatch(data, &mut acc, &mute, &audio_tx),
                    |err: cpal::StreamError| error!(?err, "cpal input stream error"),
                    None,
                )
                .context("build i16 input stream")?,
            SampleFormat::F32 => device
                .build_input_stream(
                    &config,
                    move |data: &[f32], _| {
                        let buf: Vec<i16> = data.iter().map(|&s| f32_to_i16(s)).collect();
                        dispatch(&buf, &mut acc, &mute, &audio_tx);
                    },
                    |err: cpal::StreamError| error!(?err, "cpal input stream error"),
                    None,
                )
                .context("build f32 input stream")?,
            other => return Err(anyhow!("unsupported sample format: {other:?}")),
        };
        return Ok(stream);
    }

    // ── Fallback: capture at the device's native config and resample to
    // 16 kHz mono in the callback.
    let default_cfg = device
        .default_input_config()
        .context("query default input config")?;
    let native_rate = default_cfg.sample_rate();
    let native_channels = default_cfg.channels();
    let sample_format = default_cfg.sample_format();
    let config: StreamConfig = default_cfg.config();
    info!(
        native_rate,
        native_channels,
        ?sample_format,
        mode = "native+resample",
        "recorder capture config (resampling to 16 kHz mono)"
    );

    let channels = native_channels as usize;
    let mut acc: Vec<i16> = Vec::with_capacity(RECORDER_CHUNK_SAMPLES * 2);
    let mut resampler = Resampler16k::new(native_rate)?;

    let stream = match sample_format {
        SampleFormat::I16 => device
            .build_input_stream(
                &config,
                move |data: &[i16], _| {
                    let mono = downmix_to_mono_f32(
                        &data.iter().map(|&s| i16_to_f32(s)).collect::<Vec<f32>>(),
                        channels,
                    );
                    let out = resampler.push(&mono);
                    let buf: Vec<i16> = out.iter().map(|&s| f32_to_i16(s)).collect();
                    dispatch(&buf, &mut acc, &mute, &audio_tx);
                },
                |err: cpal::StreamError| error!(?err, "cpal input stream error"),
                None,
            )
            .context("build i16 resampling input stream")?,
        SampleFormat::F32 => device
            .build_input_stream(
                &config,
                move |data: &[f32], _| {
                    let mono = downmix_to_mono_f32(data, channels);
                    let out = resampler.push(&mono);
                    let buf: Vec<i16> = out.iter().map(|&s| f32_to_i16(s)).collect();
                    dispatch(&buf, &mut acc, &mute, &audio_tx);
                },
                |err: cpal::StreamError| error!(?err, "cpal input stream error"),
                None,
            )
            .context("build f32 resampling input stream")?,
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
        assert_eq!(f32_to_i16(-2.0), -i16::MAX); // -1.0 * 32767 → -32767
        assert_eq!(f32_to_i16(2.0), i16::MAX);
        assert_eq!(f32_to_i16(0.0), 0);
    }

    #[test]
    fn i16_to_f32_maps_extremes_near_unit() {
        assert!((i16_to_f32(i16::MAX) - 1.0).abs() < 1e-6);
        assert_eq!(i16_to_f32(0), 0.0);
        assert!(i16_to_f32(i16::MIN) <= -1.0);
    }

    #[test]
    fn downmix_mono_is_passthrough() {
        let mono = vec![0.1, -0.2, 0.3];
        assert_eq!(downmix_to_mono_f32(&mono, 1), mono);
    }

    #[test]
    fn downmix_stereo_averages_channels() {
        // L,R interleaved: (1.0,-1.0) → 0.0 ; (0.5,0.5) → 0.5
        let stereo = vec![1.0, -1.0, 0.5, 0.5];
        assert_eq!(downmix_to_mono_f32(&stereo, 2), vec![0.0, 0.5]);
    }

    #[test]
    fn resampler_downsamples_48k_to_16k_roughly_one_third() {
        // Feed ~1 s of 48 kHz silence; expect ~16 k output frames (FFT
        // resampler has a little edge latency, so allow a margin).
        let mut r = Resampler16k::new(48_000).unwrap();
        let out = r.push(&vec![0.0f32; 48_000]);
        assert!(
            out.len() > 14_000 && out.len() <= 16_000,
            "got {} output frames",
            out.len()
        );
    }
}
