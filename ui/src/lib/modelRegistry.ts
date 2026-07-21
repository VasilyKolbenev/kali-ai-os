// OPUS-301: TS view of the shared model registry (config/model_registry.json).
// These constants mirror the JSON SoT byte-for-byte; a vitest sync test
// (modelRegistry.test.ts) reads the JSON and fails if they drift. Anthropic is
// the enforced provider this batch.

/** Active (supported) Anthropic models shown in the UI. */
export const ANTHROPIC_ACTIVE = [
  "claude-sonnet-5",
  "claude-opus-4-8",
  "claude-haiku-4-5-20251001",
] as const;

/** Active Anthropic default. */
export const ANTHROPIC_DEFAULT = "claude-sonnet-5";

// Deny-list = official retired snapshots ∪ legacy aliases a previous UI may have
// stored (incl. the claude-opus-4-20250414 typo). None may be a default/option.
export const ANTHROPIC_RETIRED = [
  // official retired
  "claude-sonnet-4-20250514",
  "claude-opus-4-20250514",
  "claude-3-5-haiku-20241022",
  // legacy aliases / typos
  "claude-opus-4-20250414",
  "claude-haiku-4-20250414",
] as const;

/**
 * Migrate a stored Anthropic model id: a retired id falls back to the active
 * default; anything active (or unknown) is returned unchanged.
 */
export function activeAnthropicModel(stored: string | undefined | null): string {
  if (!stored) return ANTHROPIC_DEFAULT;
  return (ANTHROPIC_RETIRED as readonly string[]).includes(stored)
    ? ANTHROPIC_DEFAULT
    : stored;
}
