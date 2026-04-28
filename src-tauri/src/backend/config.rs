use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

/// Top-level application config, mirrors kernel/models.py ConfigSchema.
/// Field names and types must match Python's model_dump output so existing
/// UI consumers don't need to change.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct AppConfig {
    #[serde(default)]
    pub server: ServerConfig,
    #[serde(default)]
    pub voice: VoiceConfig,
    #[serde(default)]
    pub llm: LlmConfig,
    #[serde(default)]
    pub schedule: ScheduleConfig,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 3005,
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct VoiceConfig {
    pub wake_word: String,
    pub mode: String,
    pub stt_model: String,
    pub tts_voice: String,
    pub vad_threshold: f32,
    pub auto_start: bool,
    // Phase 3 Chunk 7 — pipeline state-machine knobs. Rust-side only;
    // Python pipeline does not consume these (engine="rust" path).
    // All fields are `#[serde(default = ...)]` so old kali.yaml files
    // load without modification.
    #[serde(default = "default_wake_threshold")]
    pub wake_threshold: f32,
    #[serde(default = "default_wake_listen_timeout_secs")]
    pub wake_listen_timeout_secs: f32,
    #[serde(default = "default_silence_chunks_to_end")]
    pub silence_chunks_to_end: u32,
    #[serde(default = "default_min_speech_chunks")]
    pub min_speech_chunks: u32,
    // Phase 3 Chunk 8 — voice pipeline engine selector. "python" routes
    // /voice/* through Rust as a thin proxy to the existing Python
    // pipeline (legacy behaviour). "rust" makes Rust authoritative and
    // disables the Python pipeline init in `kernel/main.py`. Default
    // stays "python" until Vasily's manual rehearsal validates the
    // Rust path on real hardware.
    #[serde(default = "default_engine")]
    pub engine: String,
}

fn default_wake_threshold() -> f32 {
    0.5
}

fn default_wake_listen_timeout_secs() -> f32 {
    3.0
}

fn default_silence_chunks_to_end() -> u32 {
    30
}

fn default_min_speech_chunks() -> u32 {
    5
}

fn default_engine() -> String {
    "python".to_string()
}

impl Default for VoiceConfig {
    fn default() -> Self {
        Self {
            wake_word: "jarvis".to_string(),
            mode: "wake_word".to_string(),
            stt_model: "base".to_string(),
            tts_voice: "default".to_string(),
            vad_threshold: 0.5,
            auto_start: false,
            wake_threshold: default_wake_threshold(),
            wake_listen_timeout_secs: default_wake_listen_timeout_secs(),
            silence_chunks_to_end: default_silence_chunks_to_end(),
            min_speech_chunks: default_min_speech_chunks(),
            engine: default_engine(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct LlmConfig {
    pub cloud_provider: String,
    pub cloud_model: String,
    pub local_provider: String,
    pub local_model: String,
    pub auto_route: bool,
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            cloud_provider: "anthropic".to_string(),
            cloud_model: "claude-sonnet-4-20250514".to_string(),
            local_provider: "ollama".to_string(),
            local_model: "llama3".to_string(),
            auto_route: true,
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ScheduleConfig {
    pub morning_hour: u8,
    pub evening_hour: u8,
    #[serde(default = "default_timezone")]
    pub timezone: String,
}

fn default_timezone() -> String {
    "local".to_string()
}

impl Default for ScheduleConfig {
    fn default() -> Self {
        Self {
            morning_hour: 8,
            evening_hour: 22,
            timezone: default_timezone(),
        }
    }
}

pub fn resolve_config_path() -> PathBuf {
    std::env::var("KALI_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("../config/kali.yaml"))
}

pub fn load_from(path: &Path) -> Result<AppConfig> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("read config from {:?}", path))?;
    serde_yaml::from_str::<AppConfig>(&raw).with_context(|| format!("parse config at {:?}", path))
}

pub fn load() -> Result<AppConfig> {
    load_from(&resolve_config_path())
}
