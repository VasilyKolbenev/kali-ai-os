//! In-process pub/sub for realtime events fanned out to WebSocket clients.
//!
//! Wraps `tokio::sync::broadcast` with a typed Event API matching Python's
//! shape. Subscribers only see events published after they subscribed; a
//! slow subscriber gets `RecvError::Lagged` which the WS handler logs and
//! continues past, rather than disconnecting.

use tokio::sync::broadcast;

use crate::backend::models::Event;

/// Default bus capacity. 256 is the usual sweet spot — large enough that a
/// slow consumer can miss a whole voice-pipeline burst without dropping the
/// connection, small enough that a stalled consumer can't hoard megabytes.
pub const BUS_CAPACITY: usize = 256;

#[derive(Debug, Clone)]
pub struct EventBus {
    tx: broadcast::Sender<Event>,
}

impl EventBus {
    pub fn new() -> Self {
        let (tx, _rx) = broadcast::channel(BUS_CAPACITY);
        Self { tx }
    }

    /// Publish an event. Returns the number of active subscribers that
    /// received it; 0 is normal when nothing is connected and is NOT an
    /// error (matches Python `EventBus.publish` semantics).
    pub fn publish(&self, event: Event) -> usize {
        self.tx.send(event).unwrap_or(0)
    }

    pub fn subscribe(&self) -> broadcast::Receiver<Event> {
        self.tx.subscribe()
    }

    pub fn subscriber_count(&self) -> usize {
        self.tx.receiver_count()
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}
