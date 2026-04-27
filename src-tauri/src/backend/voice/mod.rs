//! Voice pipeline — Rust-side state machine, audio I/O, and inference
//! engines.
//!
//! Phase 3 Chunk 1 introduces only the bridge primitive. Subsequent
//! chunks fill in `tts`, `stt`, `vad`, `wake_word`, `recorder`,
//! `playback`, `state`, `pipeline`. F5-TTS Russian + ruaccent live in a
//! Python child process spoken to via [`bridge::BridgeWorker`].

pub mod bridge;
