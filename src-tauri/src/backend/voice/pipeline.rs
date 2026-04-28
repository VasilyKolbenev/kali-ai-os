//! Pipeline runner — owns concrete engines and drives the
//! [`super::state::PipelineMachine`] via an async event loop.
//!
//! Architecture
//!
//! ```text
//!   Recorder (cpal thread) ─┐
//!                            ├─► PipelineRunner.run() ──► PipelineMachine.step()
//!   Internal events ────────┘                                │
//!                                                            ├─► sync actions inline
//!                                                            └─► async actions: tokio::spawn
//!                                                                  └─► result event back via internal mpsc
//! ```
//!
//! Speaker (rodio) is `!Send` on some platforms so it lives on a
//! dedicated `std::thread`. The runner talks to it over a sync channel
//! plus a tokio `oneshot` for completion. Same pattern as Recorder.
//!
//! Wake-detect calls are gated by an `Arc<AtomicBool>` "in flight" flag
//! so a 30 ms recorder cadence does not pile up 33 concurrent bridge
//! calls per second on a worker that processes them sequentially.
//! Result: at most one wake check at a time; intermediate chunks are
//! skipped. With openwakeword's ~80-100 ms inference time on CPU, the
//! effective wake polling rate is ~10 Hz which is the upstream package's
//! own design point.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::json;
use tokio::sync::{mpsc, oneshot, watch};
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};

use crate::backend::config::VoiceConfig;
use crate::backend::event_bus::EventBus;
use crate::backend::models::Event;
use crate::backend::voice::bridge::BridgeWorker;
use crate::backend::voice::mute::MuteFlag;
use crate::backend::voice::playback::Speaker;
use crate::backend::voice::recorder::{Recorder, RECORDER_SAMPLE_RATE};
use crate::backend::voice::state::{PipelineAction, PipelineEvent, PipelineMachine, PipelineState};
use crate::backend::voice::stt::SttClient;
use crate::backend::voice::tts::TtsClient;
use crate::backend::voice::vad::{VadEngine, VAD_CHUNK_SAMPLES};
use crate::backend::voice::wake_word::WakeWordClient;

const EVENT_CHANNEL_CAPACITY: usize = 256;
const PLAYBACK_QUEUE: usize = 8;

/// Construction parameters. Intentionally explicit (no `Default`) so a
/// caller can't accidentally start a pipeline against a stale model
/// path or the wrong Python interpreter.
pub struct PipelineDeps {
    pub voice_config: VoiceConfig,
    pub vad_model_path: PathBuf,
    /// Path or name of the Python executable. Typically `../.venv/Scripts/python.exe`
    /// on Windows dev boxes, or `python3` in production bundles.
    pub python_exe: String,
    /// CWD passed to the bridge worker — must contain `kernel/` so
    /// `python -m kernel.workers.tts_worker` resolves.
    pub bridge_cwd: String,
    /// HTTP URL for the Python `/chat` endpoint. The state-machine's
    /// `Generating` state POSTs `{"text": <transcript>}` here and
    /// expects `{"response": <text>}` back.
    pub chat_url: String,
    /// Bus that downstream WS clients (Tauri UI) subscribe to. The
    /// runner publishes `voice.*` and `agent.response` events here.
    pub event_bus: EventBus,
}

/// Public handle. Spawn one per process; use `start()` / `stop()` to
/// gate the active listening window. Drop to tear down.
pub struct Pipeline {
    event_tx: mpsc::Sender<PipelineEvent>,
    state_rx: watch::Receiver<PipelineState>,
    shutdown_tx: Option<oneshot::Sender<()>>,
    join: Option<JoinHandle<()>>,
}

impl Pipeline {
    pub async fn new(deps: PipelineDeps) -> Result<Self> {
        let mute = MuteFlag::new();

        // One Python child process serves TTS + STT + wake. Correlation
        // by id keeps concurrent calls from the runner's spawned tasks
        // untangled inside `BridgeWorker`.
        let bridge = Arc::new(
            BridgeWorker::spawn(
                "ml",
                &deps.python_exe,
                &["-m", "kernel.workers.tts_worker"],
                &deps.bridge_cwd,
            )
            .await
            .context("spawn ML bridge worker")?,
        );

        let wake = WakeWordClient::new(bridge.clone());
        let stt = SttClient::new(bridge.clone());
        let tts = TtsClient::new(bridge.clone());
        let vad = VadEngine::load(&deps.vad_model_path).context("load Silero VAD")?;

        let playback = PlaybackThread::spawn(mute.clone()).context("spawn playback thread")?;
        let (recorder, audio_rx) = Recorder::start(mute.clone()).context("start recorder")?;

        let machine = PipelineMachine::new(&deps.voice_config);
        let (state_tx, state_rx) = watch::channel(machine.state());
        let (event_tx, event_rx) = mpsc::channel::<PipelineEvent>(EVENT_CHANNEL_CAPACITY);
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();

        let runner = PipelineRunner {
            machine,
            self_tx: event_tx.clone(),
            event_rx,
            state_tx,
            audio_rx,
            _recorder: recorder,
            playback,
            vad,
            mute,
            wake,
            stt,
            tts,
            event_bus: deps.event_bus,
            chat_url: deps.chat_url,
            wake_threshold: deps.voice_config.wake_threshold,
            wake_listen_timeout_secs: deps.voice_config.wake_listen_timeout_secs,
            vad_threshold: deps.voice_config.vad_threshold,
            vad_buffer: Vec::with_capacity(VAD_CHUNK_SAMPLES * 2),
            wake_timeout_handle: None,
            wake_in_flight: Arc::new(AtomicBool::new(false)),
        };

        let join = tokio::spawn(runner.run(shutdown_rx));

        Ok(Self {
            event_tx,
            state_rx,
            shutdown_tx: Some(shutdown_tx),
            join: Some(join),
        })
    }

    /// Move from `Off` to `Listening`. Idempotent — sending Start in
    /// any other state is dropped by the state machine.
    pub async fn start(&self) -> Result<()> {
        self.event_tx
            .send(PipelineEvent::Start)
            .await
            .map_err(|_| anyhow!("pipeline runner not running"))
    }

    /// Force back to `Off`. Idempotent.
    pub async fn stop(&self) -> Result<()> {
        self.event_tx
            .send(PipelineEvent::Stop)
            .await
            .map_err(|_| anyhow!("pipeline runner not running"))
    }

    pub fn current_state(&self) -> PipelineState {
        *self.state_rx.borrow()
    }

    /// Subscribe to live state changes. Hand the receiver to the Tauri
    /// UI bridge or any future `/voice/state` HTTP route.
    pub fn state_rx(&self) -> watch::Receiver<PipelineState> {
        self.state_rx.clone()
    }
}

impl Drop for Pipeline {
    fn drop(&mut self) {
        // Signal runner to exit. Don't await join — async drop isn't
        // available on stable. The task ends within milliseconds.
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(());
        }
        if let Some(h) = self.join.take() {
            h.abort();
        }
    }
}

struct PipelineRunner {
    machine: PipelineMachine,
    self_tx: mpsc::Sender<PipelineEvent>,
    event_rx: mpsc::Receiver<PipelineEvent>,
    state_tx: watch::Sender<PipelineState>,
    audio_rx: mpsc::Receiver<Vec<i16>>,
    _recorder: Recorder,
    playback: PlaybackThread,
    vad: VadEngine,
    mute: MuteFlag,
    wake: WakeWordClient,
    stt: SttClient,
    tts: TtsClient,
    event_bus: EventBus,
    chat_url: String,
    wake_threshold: f32,
    wake_listen_timeout_secs: f32,
    vad_threshold: f32,
    /// Buffer that re-frames recorder's 480-sample chunks into VAD's
    /// strict 512-sample requirement. Drained in 512-sample groups.
    vad_buffer: Vec<i16>,
    wake_timeout_handle: Option<JoinHandle<()>>,
    wake_in_flight: Arc<AtomicBool>,
}

impl PipelineRunner {
    async fn run(mut self, mut shutdown_rx: oneshot::Receiver<()>) {
        info!("voice pipeline runner started");
        loop {
            let event = tokio::select! {
                biased;
                _ = &mut shutdown_rx => break,
                chunk = self.audio_rx.recv() => match chunk {
                    Some(c) => PipelineEvent::AudioChunk(c),
                    None => {
                        warn!("recorder channel closed, exiting runner");
                        break;
                    }
                },
                ev = self.event_rx.recv() => match ev {
                    Some(e) => e,
                    None => break,
                },
            };

            let actions = self.machine.step(event);
            for action in actions {
                self.handle_action(action).await;
            }
        }
        info!("voice pipeline runner exited");
    }

    async fn handle_action(&mut self, action: PipelineAction) {
        match action {
            PipelineAction::FeedVad(samples) => {
                self.vad_buffer.extend_from_slice(&samples);
                while self.vad_buffer.len() >= VAD_CHUNK_SAMPLES {
                    let chunk: Vec<i16> = self.vad_buffer.drain(..VAD_CHUNK_SAMPLES).collect();
                    match self.vad.feed(&chunk) {
                        Ok(prob) => {
                            let active = prob > self.vad_threshold;
                            if let Err(e) = self
                                .self_tx
                                .send(PipelineEvent::VadResult { active, prob })
                                .await
                            {
                                debug!(?e, "vad result drop: runner exiting");
                            }
                        }
                        Err(e) => warn!(?e, "vad feed failed"),
                    }
                }
            }
            PipelineAction::FeedWake(samples) => {
                // Skip if a previous wake call hasn't completed — keeps
                // the bridge from queueing 33 calls/sec while openwakeword
                // takes ~80-100 ms per call.
                if self.wake_in_flight.swap(true, Ordering::AcqRel) {
                    return;
                }
                let wake = self.wake.clone();
                let tx = self.self_tx.clone();
                let threshold = self.wake_threshold;
                let in_flight = self.wake_in_flight.clone();
                tokio::spawn(async move {
                    let result = wake.detect(&samples, RECORDER_SAMPLE_RATE, threshold).await;
                    in_flight.store(false, Ordering::Release);
                    let event = match result {
                        Ok(d) if d.detected => PipelineEvent::WakeDetected {
                            confidence: d.confidence,
                            word: d.word,
                        },
                        Ok(d) => PipelineEvent::WakeNotDetected {
                            confidence: d.confidence,
                        },
                        Err(e) => {
                            warn!(?e, "wake detect failed");
                            return;
                        }
                    };
                    let _ = tx.send(event).await;
                });
            }
            PipelineAction::RunStt(audio) => {
                let stt = self.stt.clone();
                let tx = self.self_tx.clone();
                tokio::spawn(async move {
                    let event = match stt
                        .transcribe(&audio, RECORDER_SAMPLE_RATE, Some("ru"))
                        .await
                    {
                        Ok(t) => PipelineEvent::SttResult(t),
                        Err(e) => PipelineEvent::SttFailed(format!("{e}")),
                    };
                    let _ = tx.send(event).await;
                });
            }
            PipelineAction::CallChat(text) => {
                let url = self.chat_url.clone();
                let tx = self.self_tx.clone();
                tokio::spawn(async move {
                    let event = match call_chat(&url, &text).await {
                        Ok(t) => PipelineEvent::ChatResult { text: t },
                        Err(e) => PipelineEvent::ChatFailed(format!("{e}")),
                    };
                    let _ = tx.send(event).await;
                });
            }
            PipelineAction::RunTts(text) => {
                let tts = self.tts.clone();
                let tx = self.self_tx.clone();
                tokio::spawn(async move {
                    let event = match tts.speak(&text).await {
                        Ok(s) => PipelineEvent::TtsResult(s),
                        Err(e) => PipelineEvent::TtsFailed(format!("{e}")),
                    };
                    let _ = tx.send(event).await;
                });
            }
            PipelineAction::Play {
                samples,
                sample_rate,
            } => {
                let playback = self.playback.handle();
                let tx = self.self_tx.clone();
                tokio::spawn(async move {
                    let event = match playback.play(samples, sample_rate).await {
                        Ok(()) => PipelineEvent::PlaybackDone,
                        Err(e) => PipelineEvent::PlaybackFailed(format!("{e}")),
                    };
                    let _ = tx.send(event).await;
                });
            }
            PipelineAction::SetMute(b) => self.mute.set_muted(b),
            PipelineAction::ResetVad => self.vad.reset(),
            PipelineAction::ResetWakeWord => {
                let wake = self.wake.clone();
                tokio::spawn(async move {
                    if let Err(e) = wake.reset().await {
                        warn!(?e, "wake reset failed");
                    }
                });
            }
            PipelineAction::EmitBusEvent(event) => {
                let _ = self.event_bus.publish(event);
            }
            PipelineAction::BroadcastState(state) => {
                let _ = self.state_tx.send(state);
                let event = Event {
                    topic: "voice.state".into(),
                    source: "voice-pipeline".into(),
                    payload: json!({ "state": state.as_str() }),
                    timestamp: chrono::Utc::now(),
                    correlation_id: uuid::Uuid::new_v4().to_string(),
                };
                let _ = self.event_bus.publish(event);
            }
            PipelineAction::StartWakeTimeout => {
                if let Some(h) = self.wake_timeout_handle.take() {
                    h.abort();
                }
                let secs = self.wake_listen_timeout_secs;
                let tx = self.self_tx.clone();
                let h = tokio::spawn(async move {
                    tokio::time::sleep(Duration::from_secs_f32(secs)).await;
                    let _ = tx.send(PipelineEvent::WakeTimeout).await;
                });
                self.wake_timeout_handle = Some(h);
            }
            PipelineAction::CancelWakeTimeout => {
                if let Some(h) = self.wake_timeout_handle.take() {
                    h.abort();
                }
            }
        }
    }
}

#[derive(Deserialize)]
struct ChatResponse {
    response: String,
    #[serde(default)]
    #[allow(dead_code)]
    source: Option<String>,
}

async fn call_chat(url: &str, text: &str) -> Result<String> {
    let client = reqwest::Client::new();
    let resp = client
        .post(url)
        .json(&json!({ "text": text }))
        .timeout(Duration::from_secs(60))
        .send()
        .await
        .context("POST /chat")?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(anyhow!("/chat HTTP {status}: {body}"));
    }
    let body: ChatResponse = resp.json().await.context("decode /chat response")?;
    Ok(body.response)
}

// ── Playback thread ────────────────────────────────────────────────
//
// Speaker holds `MixerDeviceSink` which contains `cpal::Stream`. cpal
// streams are `!Send` on some hosts (CoreAudio in particular) so we
// own the Speaker on a dedicated `std::thread` and talk to it via
// `std::sync::mpsc` for requests + `tokio::oneshot` for completions.
// Same pattern Recorder uses.

struct PlaybackThread {
    handle: PlaybackHandle,
    _thread: Option<std::thread::JoinHandle<()>>,
}

#[derive(Clone)]
struct PlaybackHandle {
    request_tx: std::sync::mpsc::SyncSender<PlaybackRequest>,
}

enum PlaybackRequest {
    Play {
        samples: Vec<f32>,
        sr: u32,
        done_tx: oneshot::Sender<Result<()>>,
    },
    Shutdown,
}

impl PlaybackThread {
    fn spawn(mute: MuteFlag) -> Result<Self> {
        let (tx, rx) = std::sync::mpsc::sync_channel::<PlaybackRequest>(PLAYBACK_QUEUE);
        let thread = std::thread::Builder::new()
            .name("kali-playback".into())
            .spawn(move || {
                let speaker = match Speaker::new(mute) {
                    Ok(s) => s,
                    Err(e) => {
                        error!(error = %e, "playback thread: failed to open audio output");
                        return;
                    }
                };
                while let Ok(req) = rx.recv() {
                    match req {
                        PlaybackRequest::Play {
                            samples,
                            sr,
                            done_tx,
                        } => {
                            let result = speaker.play_pcm_f32(samples, sr);
                            let _ = done_tx.send(result);
                        }
                        PlaybackRequest::Shutdown => break,
                    }
                }
                info!("playback thread exiting");
            })
            .context("spawn playback thread")?;

        Ok(Self {
            handle: PlaybackHandle { request_tx: tx },
            _thread: Some(thread),
        })
    }

    fn handle(&self) -> PlaybackHandle {
        self.handle.clone()
    }
}

impl Drop for PlaybackThread {
    fn drop(&mut self) {
        let _ = self.handle.request_tx.send(PlaybackRequest::Shutdown);
        // Don't join: thread exits cleanly when channel closes.
    }
}

impl PlaybackHandle {
    async fn play(&self, samples: Vec<f32>, sr: u32) -> Result<()> {
        let (done_tx, done_rx) = oneshot::channel();
        self.request_tx
            .send(PlaybackRequest::Play {
                samples,
                sr,
                done_tx,
            })
            .map_err(|_| anyhow!("playback thread dropped"))?;
        done_rx
            .await
            .map_err(|_| anyhow!("playback canceled"))?
    }
}
