//! Pure pipeline state machine — `step(event) -> actions`. No I/O, no
//! engines, no async. The runner in [`super::pipeline`] owns the real
//! recorder/VAD/wake/STT/TTS/speaker; this module owns the transition
//! matrix and the small bag of internal counters that govern utterance
//! framing (silence run length, speech-chunk count).
//!
//! Splitting the machine from the runner means transitions are unit-
//! testable without hardware or mocks: tests just feed [`PipelineEvent`]
//! sequences and assert on resulting state + emitted [`PipelineAction`].

use serde::Serialize;
use serde_json::json;

use crate::backend::config::VoiceConfig;
use crate::backend::models::Event;
use crate::backend::voice::stt::Transcript;
use crate::backend::voice::tts::Speech;

/// Externally-visible pipeline state. Broadcast via
/// [`PipelineAction::BroadcastState`] on every transition so the UI's
/// `voice.state` event mirror stays accurate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PipelineState {
    Off,
    Listening,
    WakeDetected,
    Capturing,
    Transcribing,
    Generating,
    Speaking,
}

impl PipelineState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Listening => "listening",
            Self::WakeDetected => "wake_detected",
            Self::Capturing => "capturing",
            Self::Transcribing => "transcribing",
            Self::Generating => "generating",
            Self::Speaking => "speaking",
        }
    }
}

/// Inputs the state machine reacts to. The runner translates real-world
/// happenings (audio chunk arriving, async ML reply, timer expiring,
/// playback finishing) into one of these.
#[derive(Debug)]
pub enum PipelineEvent {
    Start,
    Stop,
    AudioChunk(Vec<i16>),
    /// Wake-word fired — runner has already applied the threshold.
    WakeDetected { confidence: f32, word: Option<String> },
    /// Wake-word checked, did not fire.
    WakeNotDetected { confidence: f32 },
    VadResult { active: bool, prob: f32 },
    SttResult(Transcript),
    SttFailed(String),
    ChatResult { text: String },
    ChatFailed(String),
    TtsResult(Speech),
    TtsFailed(String),
    PlaybackDone,
    PlaybackFailed(String),
    /// Wake-listen window expired without enough speech.
    WakeTimeout,
}

/// Side effects the runner must perform after a transition. Sync ones
/// (FeedVad, SetMute, EmitBusEvent) execute inline; async ones
/// (FeedWake, RunStt, CallChat, RunTts, Play) spawn tasks that emit
/// follow-up [`PipelineEvent`]s on completion.
#[derive(Debug)]
pub enum PipelineAction {
    /// Run wake-word detection on `samples`, emit `WakeDetected` /
    /// `WakeNotDetected` when done. Async.
    FeedWake(Vec<i16>),
    /// Run VAD on `samples`, emit `VadResult` when done. Sync (Silero
    /// returns in ~5 ms on CPU); the runner can call it inline and
    /// inject the result event without spawning.
    FeedVad(Vec<i16>),
    /// Transcribe `audio` via STT, emit `SttResult` / `SttFailed`. Async.
    RunStt(Vec<i16>),
    /// Call the Python `/chat` endpoint with `text`, emit `ChatResult`
    /// / `ChatFailed`. Async.
    CallChat(String),
    /// Synthesise TTS for `text`, emit `TtsResult` / `TtsFailed`. Async.
    RunTts(String),
    /// Play the given f32 PCM buffer, emit `PlaybackDone` /
    /// `PlaybackFailed`. Async.
    Play { samples: Vec<f32>, sample_rate: u32 },
    /// Toggle the recorder's anti-echo mute flag.
    SetMute(bool),
    /// Clear the wake-word model's hidden state (call between utterances).
    ResetWakeWord,
    /// Clear the VAD's hidden state (same reasoning).
    ResetVad,
    /// Publish a domain event on the [`crate::backend::event_bus::EventBus`]
    /// so connected WS clients see it.
    EmitBusEvent(Event),
    /// Update the `voice.state` watch channel so anything subscribing
    /// to live state (Tauri UI hooks, Rust integration tests) sees the
    /// transition.
    BroadcastState(PipelineState),
    /// Arm a `wake_listen_timeout_secs` timer that, when it fires,
    /// emits [`PipelineEvent::WakeTimeout`].
    StartWakeTimeout,
    /// Cancel any pending wake-timeout timer.
    CancelWakeTimeout,
}

/// Mutable counters and buffers used during transitions. Lives inside
/// [`PipelineMachine`]; not exposed directly so transitions stay
/// authoritative over its evolution.
#[derive(Debug, Default)]
struct PipelineCtx {
    /// Frames of consecutive silence inside `Capturing`. Resets on speech.
    silence_count: u32,
    /// Frames classified as speech inside `Capturing`. Used as the
    /// "we actually heard something" gate before STT fires.
    speech_chunks: u32,
    /// Audio collected during `Capturing` that will be transcribed. Holds
    /// raw 16 kHz mono i16. Cleared on each capture-window restart.
    capture_buffer: Vec<i16>,
}

/// State machine. Combine with the [`super::pipeline::Pipeline`] runner
/// or drive directly from tests.
#[derive(Debug)]
pub struct PipelineMachine {
    state: PipelineState,
    ctx: PipelineCtx,
    cfg: VoiceConfigSnapshot,
}

/// Tiny copy of the config knobs the state machine actually consults
/// during transitions. The wake-word threshold lives in the runner
/// (passed to `wake.detect(threshold)`) — the state machine only sees
/// the post-threshold `WakeDetected` / `WakeNotDetected` events.
#[derive(Debug, Clone)]
struct VoiceConfigSnapshot {
    silence_chunks_to_end: u32,
    min_speech_chunks: u32,
}

impl From<&VoiceConfig> for VoiceConfigSnapshot {
    fn from(cfg: &VoiceConfig) -> Self {
        Self {
            silence_chunks_to_end: cfg.silence_chunks_to_end,
            min_speech_chunks: cfg.min_speech_chunks,
        }
    }
}

impl PipelineMachine {
    pub fn new(cfg: &VoiceConfig) -> Self {
        Self {
            state: PipelineState::Off,
            ctx: PipelineCtx::default(),
            cfg: VoiceConfigSnapshot::from(cfg),
        }
    }

    pub fn state(&self) -> PipelineState {
        self.state
    }

    /// Test-only inspector for the running silence-frame counter.
    #[cfg(test)]
    pub(crate) fn silence_count(&self) -> u32 {
        self.ctx.silence_count
    }

    /// Test-only inspector for the running speech-frame counter.
    #[cfg(test)]
    pub(crate) fn speech_chunks(&self) -> u32 {
        self.ctx.speech_chunks
    }

    /// Test-only inspector for the capture buffer length (samples).
    #[cfg(test)]
    pub(crate) fn capture_buffer_len(&self) -> usize {
        self.ctx.capture_buffer.len()
    }

    pub fn step(&mut self, event: PipelineEvent) -> Vec<PipelineAction> {
        let mut actions = Vec::new();

        match (self.state, event) {
            // ── Off ──────────────────────────────────────────────
            (PipelineState::Off, PipelineEvent::Start) => {
                self.state = PipelineState::Listening;
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(true)));
            }
            (PipelineState::Off, _) => {
                // Pipeline not started — ignore everything else.
            }

            // ── Listening ────────────────────────────────────────
            (PipelineState::Listening, PipelineEvent::AudioChunk(chunk)) => {
                actions.push(PipelineAction::FeedWake(chunk));
            }
            (
                PipelineState::Listening,
                PipelineEvent::WakeDetected { confidence, word },
            ) => {
                self.state = PipelineState::WakeDetected;
                self.ctx.silence_count = 0;
                self.ctx.speech_chunks = 0;
                self.ctx.capture_buffer.clear();
                actions.push(PipelineAction::EmitBusEvent(voice_wake_word_event(
                    word, confidence,
                )));
                actions.push(PipelineAction::BroadcastState(PipelineState::WakeDetected));
                actions.push(PipelineAction::ResetVad);
                actions.push(PipelineAction::StartWakeTimeout);
            }
            (PipelineState::Listening, PipelineEvent::WakeNotDetected { .. }) => {
                // Wake check came back negative — keep listening, no action.
            }
            (PipelineState::Listening, PipelineEvent::Stop) => {
                self.state = PipelineState::Off;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::CancelWakeTimeout);
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(false)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Off));
            }
            (PipelineState::Listening, _) => {}

            // ── WakeDetected (transient) ─────────────────────────
            (PipelineState::WakeDetected, PipelineEvent::AudioChunk(chunk)) => {
                self.state = PipelineState::Capturing;
                self.ctx.capture_buffer.extend_from_slice(&chunk);
                actions.push(PipelineAction::BroadcastState(PipelineState::Capturing));
                actions.push(PipelineAction::FeedVad(chunk));
            }
            (PipelineState::WakeDetected, PipelineEvent::WakeTimeout) => {
                self.state = PipelineState::Listening;
                self.ctx.capture_buffer.clear();
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::WakeDetected, PipelineEvent::Stop) => {
                self.state = PipelineState::Off;
                self.ctx.capture_buffer.clear();
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::CancelWakeTimeout);
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(false)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Off));
            }
            (PipelineState::WakeDetected, _) => {}

            // ── Capturing ────────────────────────────────────────
            (PipelineState::Capturing, PipelineEvent::AudioChunk(chunk)) => {
                self.ctx.capture_buffer.extend_from_slice(&chunk);
                actions.push(PipelineAction::FeedVad(chunk));
            }
            (PipelineState::Capturing, PipelineEvent::VadResult { active, .. }) => {
                if active {
                    self.ctx.speech_chunks += 1;
                    self.ctx.silence_count = 0;
                } else {
                    self.ctx.silence_count += 1;
                    if self.ctx.silence_count >= self.cfg.silence_chunks_to_end
                        && self.ctx.speech_chunks >= self.cfg.min_speech_chunks
                    {
                        let buffer = std::mem::take(&mut self.ctx.capture_buffer);
                        self.state = PipelineState::Transcribing;
                        actions.push(PipelineAction::CancelWakeTimeout);
                        actions
                            .push(PipelineAction::BroadcastState(PipelineState::Transcribing));
                        actions.push(PipelineAction::RunStt(buffer));
                    }
                }
            }
            (PipelineState::Capturing, PipelineEvent::WakeTimeout) => {
                self.state = PipelineState::Listening;
                self.ctx.capture_buffer.clear();
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::Capturing, PipelineEvent::Stop) => {
                self.state = PipelineState::Off;
                self.ctx.capture_buffer.clear();
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::CancelWakeTimeout);
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(false)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Off));
            }
            (PipelineState::Capturing, _) => {}

            // ── Transcribing ─────────────────────────────────────
            (PipelineState::Transcribing, PipelineEvent::SttResult(transcript)) => {
                self.state = PipelineState::Generating;
                let text = transcript.text.clone();
                actions.push(PipelineAction::EmitBusEvent(voice_transcribed_event(
                    &transcript,
                )));
                actions.push(PipelineAction::BroadcastState(PipelineState::Generating));
                actions.push(PipelineAction::CallChat(text));
            }
            (PipelineState::Transcribing, PipelineEvent::SttFailed(_)) => {
                self.state = PipelineState::Listening;
                self.ctx.capture_buffer.clear();
                self.ctx.silence_count = 0;
                self.ctx.speech_chunks = 0;
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::Transcribing, PipelineEvent::Stop) => {
                self.state = PipelineState::Off;
                self.ctx.capture_buffer.clear();
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(false)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Off));
            }
            (PipelineState::Transcribing, _) => {}

            // ── Generating ───────────────────────────────────────
            (PipelineState::Generating, PipelineEvent::ChatResult { text }) => {
                self.state = PipelineState::Speaking;
                let tts_text = text.clone();
                actions.push(PipelineAction::EmitBusEvent(agent_response_event(&text)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Speaking));
                actions.push(PipelineAction::SetMute(true));
                actions.push(PipelineAction::RunTts(tts_text));
            }
            (PipelineState::Generating, PipelineEvent::ChatFailed(_)) => {
                self.state = PipelineState::Listening;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::Generating, PipelineEvent::Stop) => {
                self.state = PipelineState::Off;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(false)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Off));
            }
            (PipelineState::Generating, _) => {}

            // ── Speaking ─────────────────────────────────────────
            (PipelineState::Speaking, PipelineEvent::TtsResult(speech)) => {
                actions.push(PipelineAction::Play {
                    samples: speech.samples,
                    sample_rate: speech.sample_rate,
                });
            }
            (PipelineState::Speaking, PipelineEvent::TtsFailed(_)) => {
                self.state = PipelineState::Listening;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::Speaking, PipelineEvent::PlaybackDone) => {
                self.state = PipelineState::Listening;
                self.ctx.silence_count = 0;
                self.ctx.speech_chunks = 0;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::ResetWakeWord);
                actions.push(PipelineAction::ResetVad);
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::Speaking, PipelineEvent::PlaybackFailed(_)) => {
                self.state = PipelineState::Listening;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::BroadcastState(PipelineState::Listening));
            }
            (PipelineState::Speaking, PipelineEvent::AudioChunk(_)) => {
                // Mute should have zeroed the chunk at the recorder
                // already; defence in depth — drop it here too.
            }
            (PipelineState::Speaking, PipelineEvent::Stop) => {
                self.state = PipelineState::Off;
                actions.push(PipelineAction::SetMute(false));
                actions.push(PipelineAction::EmitBusEvent(voice_pipeline_event(false)));
                actions.push(PipelineAction::BroadcastState(PipelineState::Off));
            }
            (PipelineState::Speaking, _) => {}
        }

        actions
    }
}

fn voice_pipeline_event(active: bool) -> Event {
    Event {
        topic: "voice.pipeline".into(),
        source: "voice-pipeline".into(),
        payload: json!({ "active": active, "mode": "wake_word" }),
        timestamp: chrono::Utc::now(),
        correlation_id: uuid::Uuid::new_v4().to_string(),
    }
}

fn voice_wake_word_event(word: Option<String>, confidence: f32) -> Event {
    Event {
        topic: "voice.wake_word".into(),
        source: "voice-pipeline".into(),
        payload: json!({ "word": word, "confidence": confidence }),
        timestamp: chrono::Utc::now(),
        correlation_id: uuid::Uuid::new_v4().to_string(),
    }
}

fn voice_transcribed_event(transcript: &Transcript) -> Event {
    Event {
        topic: "voice.transcribed".into(),
        source: "voice-pipeline".into(),
        payload: json!({
            "text": transcript.text,
            "language": transcript.language,
            "duration_ms": transcript.duration_ms,
        }),
        timestamp: chrono::Utc::now(),
        correlation_id: uuid::Uuid::new_v4().to_string(),
    }
}

fn agent_response_event(text: &str) -> Event {
    Event {
        topic: "agent.response".into(),
        source: "voice-pipeline".into(),
        payload: json!({ "text": text }),
        timestamp: chrono::Utc::now(),
        correlation_id: uuid::Uuid::new_v4().to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn machine() -> PipelineMachine {
        PipelineMachine::new(&VoiceConfig::default())
    }

    fn started() -> PipelineMachine {
        let mut m = machine();
        m.step(PipelineEvent::Start);
        m
    }

    fn in_capturing() -> PipelineMachine {
        let mut m = started();
        m.step(PipelineEvent::WakeDetected {
            confidence: 0.9,
            word: Some("hey_jarvis_v0.1".into()),
        });
        // WakeDetected → Capturing happens on next AudioChunk per the
        // 7-state transition graph; push one to land in Capturing.
        m.step(PipelineEvent::AudioChunk(vec![0i16; 480]));
        m
    }

    fn has_action<F: Fn(&PipelineAction) -> bool>(actions: &[PipelineAction], f: F) -> bool {
        actions.iter().any(f)
    }

    #[test]
    fn off_then_start_transitions_to_listening_and_emits_pipeline_active() {
        let mut m = machine();
        assert_eq!(m.state(), PipelineState::Off);
        let actions = m.step(PipelineEvent::Start);
        assert_eq!(m.state(), PipelineState::Listening);
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::BroadcastState(PipelineState::Listening))));
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::EmitBusEvent(e) if e.topic == "voice.pipeline")));
    }

    #[test]
    fn off_ignores_audio_and_other_events() {
        let mut m = machine();
        let actions = m.step(PipelineEvent::AudioChunk(vec![0; 480]));
        assert_eq!(m.state(), PipelineState::Off);
        assert!(actions.is_empty());
    }

    #[test]
    fn listening_audio_chunk_feeds_wake_word_only() {
        let mut m = started();
        let chunk = vec![0i16; 480];
        let actions = m.step(PipelineEvent::AudioChunk(chunk));
        assert_eq!(m.state(), PipelineState::Listening);
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::FeedWake(_))));
        assert!(!has_action(&actions, |a| matches!(a, PipelineAction::FeedVad(_))));
    }

    #[test]
    fn listening_wake_detected_transitions_to_wake_detected_state() {
        let mut m = started();
        let actions = m.step(PipelineEvent::WakeDetected {
            confidence: 0.9,
            word: Some("hey_jarvis_v0.1".into()),
        });
        assert_eq!(m.state(), PipelineState::WakeDetected);
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::EmitBusEvent(e) if e.topic == "voice.wake_word")));
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::BroadcastState(PipelineState::WakeDetected))));
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::ResetVad)));
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::StartWakeTimeout)));
    }

    #[test]
    fn listening_wake_not_detected_is_a_noop() {
        let mut m = started();
        let actions = m.step(PipelineEvent::WakeNotDetected { confidence: 0.05 });
        assert_eq!(m.state(), PipelineState::Listening);
        assert!(actions.is_empty());
    }

    #[test]
    fn wake_detected_first_audio_chunk_enters_capturing() {
        let mut m = started();
        m.step(PipelineEvent::WakeDetected {
            confidence: 0.9,
            word: None,
        });
        assert_eq!(m.state(), PipelineState::WakeDetected);
        let actions = m.step(PipelineEvent::AudioChunk(vec![0i16; 480]));
        assert_eq!(m.state(), PipelineState::Capturing);
        // Capturing must feed VAD on every chunk.
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::FeedVad(_))));
    }

    #[test]
    fn wake_detected_timeout_resets_to_listening() {
        let mut m = started();
        m.step(PipelineEvent::WakeDetected {
            confidence: 0.9,
            word: None,
        });
        let actions = m.step(PipelineEvent::WakeTimeout);
        assert_eq!(m.state(), PipelineState::Listening);
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::BroadcastState(PipelineState::Listening))));
    }

    #[test]
    fn capturing_audio_chunk_appends_to_buffer() {
        let mut m = in_capturing();
        let len_before = m.capture_buffer_len();
        m.step(PipelineEvent::AudioChunk(vec![1i16; 480]));
        assert_eq!(m.capture_buffer_len(), len_before + 480);
        assert_eq!(m.state(), PipelineState::Capturing);
    }

    #[test]
    fn capturing_vad_active_increments_speech_count_and_resets_silence() {
        let mut m = in_capturing();
        // Drive some silence first.
        m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        assert_eq!(m.silence_count(), 2);
        m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        assert_eq!(m.speech_chunks(), 1);
        assert_eq!(m.silence_count(), 0);
        assert_eq!(m.state(), PipelineState::Capturing);
    }

    #[test]
    fn capturing_long_silence_without_enough_speech_does_not_transcribe() {
        let mut m = in_capturing();
        // Only 2 speech frames — under min_speech_chunks (5).
        m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        // Lots of silence — over silence_chunks_to_end (30).
        for _ in 0..40 {
            m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        }
        // Must NOT transition (insufficient speech, treated as noise).
        assert_eq!(m.state(), PipelineState::Capturing);
    }

    #[test]
    fn capturing_speech_then_silence_triggers_transcribe_with_buffer() {
        let mut m = in_capturing();
        // 6 speech frames (>= min_speech_chunks=5).
        for _ in 0..6 {
            m.step(PipelineEvent::AudioChunk(vec![1i16; 480]));
            m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        }
        let buffered = m.capture_buffer_len();
        assert!(buffered >= 480 * 6, "expected buffer to hold all chunks");

        // 30 silent frames — final one must trigger transcribe.
        let mut transitioned = false;
        let mut last_actions = Vec::new();
        for _ in 0..30 {
            last_actions = m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
            if m.state() == PipelineState::Transcribing {
                transitioned = true;
                break;
            }
        }
        assert!(transitioned, "should have transitioned to Transcribing");
        assert!(has_action(&last_actions, |a| matches!(a, PipelineAction::RunStt(buf) if !buf.is_empty())));
        assert!(has_action(&last_actions, |a| matches!(a, PipelineAction::CancelWakeTimeout)));
        assert!(has_action(&last_actions, |a| matches!(a,
            PipelineAction::BroadcastState(PipelineState::Transcribing))));
    }

    #[test]
    fn transcribing_stt_result_transitions_to_generating_and_calls_chat() {
        // Bypass Capturing manually: in_capturing is Capturing, so we
        // need to push it through to Transcribing first. Easiest: send
        // an SttResult while still in Capturing — should be a no-op
        // (wrong state). Then push state forward properly.
        let mut m = in_capturing();
        // Drive into Transcribing by satisfying speech + silence gates.
        for _ in 0..6 {
            m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        }
        for _ in 0..30 {
            m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        }
        assert_eq!(m.state(), PipelineState::Transcribing);

        let actions = m.step(PipelineEvent::SttResult(Transcript {
            text: "привет жарвис".into(),
            language: Some("ru".into()),
            duration_ms: Some(1500),
        }));
        assert_eq!(m.state(), PipelineState::Generating);
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::EmitBusEvent(e) if e.topic == "voice.transcribed")));
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::CallChat(_))));
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::BroadcastState(PipelineState::Generating))));
    }

    #[test]
    fn transcribing_stt_failed_falls_back_to_listening() {
        let mut m = in_capturing();
        for _ in 0..6 {
            m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        }
        for _ in 0..30 {
            m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        }
        assert_eq!(m.state(), PipelineState::Transcribing);

        let actions = m.step(PipelineEvent::SttFailed("model crashed".into()));
        assert_eq!(m.state(), PipelineState::Listening);
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::BroadcastState(PipelineState::Listening))));
    }

    #[test]
    fn generating_chat_result_transitions_to_speaking_with_mute_and_tts() {
        let mut m = in_capturing();
        for _ in 0..6 {
            m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        }
        for _ in 0..30 {
            m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        }
        m.step(PipelineEvent::SttResult(Transcript {
            text: "hi".into(),
            language: Some("en".into()),
            duration_ms: Some(500),
        }));
        assert_eq!(m.state(), PipelineState::Generating);

        let actions = m.step(PipelineEvent::ChatResult { text: "Привет!".into() });
        assert_eq!(m.state(), PipelineState::Speaking);
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::SetMute(true))));
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::RunTts(_))));
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::EmitBusEvent(e) if e.topic == "agent.response")));
    }

    #[test]
    fn speaking_audio_chunks_are_ignored() {
        let mut m = in_capturing();
        for _ in 0..6 {
            m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        }
        for _ in 0..30 {
            m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        }
        m.step(PipelineEvent::SttResult(Transcript {
            text: "hi".into(),
            language: Some("en".into()),
            duration_ms: Some(500),
        }));
        m.step(PipelineEvent::ChatResult { text: "ok".into() });
        assert_eq!(m.state(), PipelineState::Speaking);

        let actions = m.step(PipelineEvent::AudioChunk(vec![1i16; 480]));
        assert_eq!(m.state(), PipelineState::Speaking);
        assert!(actions.is_empty(), "speaking must not react to mic input");
    }

    #[test]
    fn speaking_playback_done_returns_to_listening_and_clears_mute() {
        let mut m = in_capturing();
        for _ in 0..6 {
            m.step(PipelineEvent::VadResult { active: true, prob: 0.9 });
        }
        for _ in 0..30 {
            m.step(PipelineEvent::VadResult { active: false, prob: 0.05 });
        }
        m.step(PipelineEvent::SttResult(Transcript {
            text: "hi".into(),
            language: Some("en".into()),
            duration_ms: Some(500),
        }));
        m.step(PipelineEvent::ChatResult { text: "ok".into() });
        m.step(PipelineEvent::TtsResult(Speech {
            samples: vec![0.0; 24_000],
            sample_rate: 24_000,
            duration_ms: 1000,
        }));
        assert_eq!(m.state(), PipelineState::Speaking);

        let actions = m.step(PipelineEvent::PlaybackDone);
        assert_eq!(m.state(), PipelineState::Listening);
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::SetMute(false))));
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::ResetWakeWord)));
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::ResetVad)));
    }

    #[test]
    fn stop_from_any_state_returns_to_off_with_pipeline_inactive() {
        // From Capturing.
        let mut m = in_capturing();
        let actions = m.step(PipelineEvent::Stop);
        assert_eq!(m.state(), PipelineState::Off);
        assert!(has_action(&actions, |a| matches!(a, PipelineAction::SetMute(false))));
        assert!(has_action(&actions, |a| matches!(a,
            PipelineAction::EmitBusEvent(e) if e.topic == "voice.pipeline")));
    }
}
