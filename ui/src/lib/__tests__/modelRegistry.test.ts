// OPUS-301: TS registry invariants + retired-id migration. The byte-for-byte
// cross-file sync with the JSON SoT (config/model_registry.json) is enforced by
// the required gate scripts/check_model_registry.py (it reads the real JSON);
// this suite covers the pure UI-facing invariants and migration logic.
import { describe, expect, it } from "vitest";

import {
  ANTHROPIC_ACTIVE,
  ANTHROPIC_DEFAULT,
  ANTHROPIC_RETIRED,
  activeAnthropicModel,
} from "../modelRegistry";

describe("modelRegistry invariants", () => {
  it("default is an active model", () => {
    expect(ANTHROPIC_ACTIVE).toContain(ANTHROPIC_DEFAULT);
  });

  it("no retired id leaks into the active list", () => {
    for (const r of ANTHROPIC_RETIRED) {
      expect(ANTHROPIC_ACTIVE).not.toContain(r);
    }
  });

  it("deny-list holds official retired + legacy typo aliases", () => {
    // official retired snapshots
    expect(ANTHROPIC_RETIRED).toContain("claude-sonnet-4-20250514");
    expect(ANTHROPIC_RETIRED).toContain("claude-opus-4-20250514");
    // legacy UI typos a previous build may have stored
    expect(ANTHROPIC_RETIRED).toContain("claude-opus-4-20250414");
    expect(ANTHROPIC_RETIRED).toContain("claude-haiku-4-20250414");
  });
});

describe("activeAnthropicModel migration", () => {
  it.each([
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-opus-4-20250414",
  ])("migrates retired/legacy id %s to the default", (id) => {
    expect(activeAnthropicModel(id)).toBe(ANTHROPIC_DEFAULT);
  });

  it("leaves an active id unchanged", () => {
    expect(activeAnthropicModel("claude-opus-4-8")).toBe("claude-opus-4-8");
  });

  it("falls back to default for empty/undefined", () => {
    expect(activeAnthropicModel(undefined)).toBe(ANTHROPIC_DEFAULT);
    expect(activeAnthropicModel("")).toBe(ANTHROPIC_DEFAULT);
  });
});
