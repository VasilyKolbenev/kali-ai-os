//! Audio playback via [`rodio`] — TTS waveforms and `jarvis_sounds/`
//! WAV clips. Owns a `MixerDeviceSink` (cpal output stream) and asserts
//! the [`MuteFlag`] for the duration of each play call so the recorder
//! doesn't capture our own output.
//!
//! ## Naming
//!
//! `rodio` 0.22 exports a `Player` type already (the playback queue
//! controller). We name ours `Speaker` to avoid a path conflict and
//! because semantically it represents "where sound comes out", not the
//! queue itself.

use std::fs::File;
use std::io::BufReader;
use std::num::NonZero;
use std::path::Path;

use anyhow::{anyhow, Context, Result};
use rodio::buffer::SamplesBuffer;
use rodio::{DeviceSinkBuilder, MixerDeviceSink, Player as RodioPlayer};

use crate::backend::voice::mute::MuteFlag;

/// RAII guard: asserts the mute flag on construction, clears it on
/// drop. Drop runs on panic too, so a TTS path that throws still
/// returns the recorder to listening.
pub(crate) struct MutedGuard<'a> {
    flag: &'a MuteFlag,
}

impl<'a> MutedGuard<'a> {
    pub(crate) fn new(flag: &'a MuteFlag) -> Self {
        flag.set_muted(true);
        Self { flag }
    }
}

impl<'a> Drop for MutedGuard<'a> {
    fn drop(&mut self) {
        self.flag.set_muted(false);
    }
}

/// Pure helper: wrap `samples` in a `SamplesBuffer` source at the
/// given sample rate, mono. `Err` only when `sample_rate == 0`
/// (rodio's `NonZero` requirement).
pub(crate) fn build_pcm_source(
    samples: Vec<f32>,
    sample_rate: u32,
) -> Result<SamplesBuffer> {
    let channels = NonZero::<u16>::new(1).expect("1 != 0");
    let sr = NonZero::<u32>::new(sample_rate)
        .ok_or_else(|| anyhow!("sample rate must be > 0, got {sample_rate}"))?;
    Ok(SamplesBuffer::new(channels, sr, samples))
}

/// Audio output handle. One per process — opens the default device
/// once, then plays sounds sequentially via `rodio::Player::append`.
pub struct Speaker {
    sink: MixerDeviceSink,
    mute: MuteFlag,
}

impl Speaker {
    /// Open the default audio output device. Fails if no device
    /// available or the OS denies access (Windows audio service down,
    /// Linux PulseAudio missing, etc.).
    pub fn new(mute: MuteFlag) -> Result<Self> {
        let sink = DeviceSinkBuilder::open_default_sink()
            .map_err(|e| anyhow!("open default audio sink: {e}"))?;
        Ok(Self { sink, mute })
    }

    /// Play raw f32 PCM samples (mono, `sample_rate` Hz). Blocks until
    /// playback ends. Mute flag is asserted for the duration.
    pub fn play_pcm_f32(&self, samples: Vec<f32>, sample_rate: u32) -> Result<()> {
        let _guard = MutedGuard::new(&self.mute);
        let source = build_pcm_source(samples, sample_rate)?;
        let player = RodioPlayer::connect_new(self.sink.mixer());
        player.append(source);
        player.sleep_until_end();
        Ok(())
    }

    /// Play a WAV file (typically a clip from `jarvis_sounds/`).
    /// Blocks until done. Mute flag asserted for the duration.
    pub fn play_wav_file(&self, path: &Path) -> Result<()> {
        let _guard = MutedGuard::new(&self.mute);
        let file = File::open(path)
            .with_context(|| format!("open audio file {}", path.display()))?;
        let player = rodio::play(self.sink.mixer(), BufReader::new(file))
            .map_err(|e| anyhow!("rodio::play {}: {e}", path.display()))?;
        player.sleep_until_end();
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rodio::Source;
    use std::time::Duration;

    #[test]
    fn build_pcm_source_one_second_at_16khz() {
        let samples = vec![0.0f32; 16_000];
        let buf = build_pcm_source(samples, 16_000).expect("ok");
        assert_eq!(buf.channels().get(), 1);
        assert_eq!(buf.sample_rate().get(), 16_000);
        assert_eq!(buf.total_duration(), Some(Duration::from_secs(1)));
    }

    #[test]
    fn build_pcm_source_24khz_keeps_rate() {
        let samples = vec![0.0f32; 24_000];
        let buf = build_pcm_source(samples, 24_000).expect("ok");
        assert_eq!(buf.sample_rate().get(), 24_000);
        assert_eq!(buf.total_duration(), Some(Duration::from_secs(1)));
    }

    #[test]
    fn build_pcm_source_zero_sample_rate_errors() {
        let err = build_pcm_source(vec![0.0; 100], 0).expect_err("must reject 0 Hz");
        assert!(err.to_string().to_lowercase().contains("sample rate"));
    }

    #[test]
    fn muted_guard_sets_mute_on_construct() {
        let flag = MuteFlag::new();
        assert!(!flag.is_muted());
        let _guard = MutedGuard::new(&flag);
        assert!(flag.is_muted(), "guard must set mute on construct");
    }

    #[test]
    fn muted_guard_clears_mute_on_drop() {
        let flag = MuteFlag::new();
        {
            let _guard = MutedGuard::new(&flag);
            assert!(flag.is_muted());
        }
        assert!(!flag.is_muted(), "guard must clear mute on drop");
    }

    #[test]
    fn muted_guard_clears_mute_even_if_already_muted_outside() {
        // Start muted (e.g. another guard upstream). Inner guard's drop
        // will overwrite to `false`. This is intentional simple
        // behaviour — nesting guards is not part of Phase 3.
        let flag = MuteFlag::new();
        flag.set_muted(true);
        {
            let _guard = MutedGuard::new(&flag);
            assert!(flag.is_muted());
        }
        assert!(!flag.is_muted());
    }
}

