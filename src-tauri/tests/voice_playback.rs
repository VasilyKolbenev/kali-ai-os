//! Playback manual test — generates a 1 s 440 Hz tone and plays it
//! via the default audio output. There is no programmatic assertion of
//! audibility; the success criterion is "Vasily heard a clean 1 s tone
//! at 440 Hz (concert A)". The test only asserts that the playback
//! call returned `Ok` and the mute flag was cleared on exit.
//!
//! Gated behind `audio-tests` so default `cargo test` never opens the
//! audio device. Run on demand:
//!     cargo test --test voice_playback --features audio-tests -- --nocapture

#![cfg(feature = "audio-tests")]

use std::f32::consts::PI;

use kali_desktop::backend::voice::mute::MuteFlag;
use kali_desktop::backend::voice::playback::Speaker;

const SAMPLE_RATE: u32 = 16_000;
const TONE_HZ: f32 = 440.0;
const TONE_DURATION_SECS: f32 = 1.0;
const TONE_AMPLITUDE: f32 = 0.25; // -12 dBFS, polite for a manual test

#[test]
fn manual_440hz_tone_plays_for_one_second() {
    let total_samples = (SAMPLE_RATE as f32 * TONE_DURATION_SECS) as usize;
    let samples: Vec<f32> = (0..total_samples)
        .map(|i| {
            let t = i as f32 / SAMPLE_RATE as f32;
            (2.0 * PI * TONE_HZ * t).sin() * TONE_AMPLITUDE
        })
        .collect();

    let mute = MuteFlag::new();
    let mute_observer = mute.clone();

    let speaker = match Speaker::new(mute) {
        Ok(s) => s,
        Err(err) => {
            eprintln!("[skip] no audio output device: {err:#}");
            return;
        }
    };

    assert!(!mute_observer.is_muted(), "mute should start cleared");
    eprintln!("Playing 1 s 440 Hz tone — listen for a clean steady pitch");
    speaker
        .play_pcm_f32(samples, SAMPLE_RATE)
        .expect("play_pcm_f32 should succeed on a working output device");
    assert!(
        !mute_observer.is_muted(),
        "mute must be cleared after play_pcm_f32 returns",
    );
}
