//! Wire shapes for events and WebSocket messages. Must match Python's
//! `kernel/models.py` so the UI sees the same frames regardless of which
//! backend terminates the WebSocket.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Event envelope published on the bus. Mirrors Pydantic `Event`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub topic: String,
    pub source: String,
    pub payload: serde_json::Value,
    #[serde(default = "Utc::now")]
    pub timestamp: DateTime<Utc>,
    #[serde(default = "new_uuid")]
    pub correlation_id: String,
}

fn new_uuid() -> String {
    Uuid::new_v4().to_string()
}

/// Frame exchanged over the WebSocket. Mirrors Pydantic `WSMessage`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WsMessage {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub data: serde_json::Value,
}

impl From<&Event> for WsMessage {
    fn from(e: &Event) -> Self {
        Self {
            kind: e.topic.clone(),
            data: e.payload.clone(),
        }
    }
}
