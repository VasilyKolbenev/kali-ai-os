/// Notifications per agent block (≥ the max per-agent fire budget of 56).
const int blockSlots = 256;

/// Deterministic 256-slot id block for [agentName]. base = (hash15 << 8); max
/// 0x7FFF00 ≈ 8.39M, well within int32. Collisions possible at hundreds of
/// distinct names (15-bit birthday bound) — acceptable on a phone; a collision
/// degrades to a shared block, never crashes.
int blockBase(String agentName) {
  var h = 0;
  for (final c in agentName.codeUnits) {
    h = (h * 31 + c) & 0x7FFF;
  }
  return h << 8;
}

/// The notification id for fire-slot [index] (0..255) of [agentName].
int slotId(String agentName, int index) => blockBase(agentName) + index;
