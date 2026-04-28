//! Anti-echo mute flag — shared `Arc<AtomicBool>` between the recorder
//! and the playback `Player`. While the player is emitting TTS audio,
//! the recorder zeros its outgoing chunks so the mic doesn't capture
//! the speaker output and feed it back into wake/VAD/STT.
//!
//! This is the dumb-but-correct baseline. Hardware echo cancellation
//! (e.g. `webrtc-audio-processing`) is explicitly out of scope for
//! Phase 3 — see the chunk plan's risk matrix.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// Cheap-to-clone shared boolean. All clones see the same flag.
#[derive(Clone, Debug, Default)]
pub struct MuteFlag(Arc<AtomicBool>);

impl MuteFlag {
    pub fn new() -> Self {
        Self(Arc::new(AtomicBool::new(false)))
    }

    pub fn is_muted(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }

    pub fn set_muted(&self, muted: bool) {
        self.0.store(muted, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_starts_unmuted() {
        let flag = MuteFlag::new();
        assert!(!flag.is_muted(), "new MuteFlag should start unmuted");
    }

    #[test]
    fn set_then_get_round_trip() {
        let flag = MuteFlag::new();
        flag.set_muted(true);
        assert!(flag.is_muted());
        flag.set_muted(false);
        assert!(!flag.is_muted());
    }

    #[test]
    fn clone_shares_state() {
        let original = MuteFlag::new();
        let clone = original.clone();
        original.set_muted(true);
        assert!(
            clone.is_muted(),
            "clones must observe writes through the original",
        );
        clone.set_muted(false);
        assert!(
            !original.is_muted(),
            "writes through the clone must reach the original",
        );
    }

    #[test]
    fn default_matches_new() {
        let from_default = MuteFlag::default();
        let from_new = MuteFlag::new();
        assert_eq!(from_default.is_muted(), from_new.is_muted());
        from_default.set_muted(true);
        assert!(from_default.is_muted());
        assert!(
            !from_new.is_muted(),
            "Default::default and ::new must produce independent flags",
        );
    }
}

