//! Voice pipeline — Rust-side state machine, audio I/O, and inference
//! engines.
//!
//! Phase 3 Chunk 1 introduces only the bridge primitive. Subsequent
//! chunks fill in `tts`, `stt`, `vad`, `wake_word`, `recorder`,
//! `playback`, `state`, `pipeline`. F5-TTS Russian + ruaccent live in a
//! Python child process spoken to via [`bridge::BridgeWorker`].

pub mod bridge;
pub mod mute;
pub mod pipeline;
pub mod playback;
pub mod recorder;
pub mod state;
pub mod stt;
pub mod tts;
pub mod vad;
pub mod wake_word;
