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

  it("the known retired default is actually retired", () => {
    expect(ANTHROPIC_RETIRED).toContain("claude-sonnet-4-20250514");
  });
});

describe("activeAnthropicModel migration", () => {
  it("migrates a retired id to the default", () => {
    expect(activeAnthropicModel("claude-sonnet-4-20250514")).toBe(ANTHROPIC_DEFAULT);
  });

  it("leaves an active id unchanged", () => {
    expect(activeAnthropicModel("claude-opus-4-8")).toBe("claude-opus-4-8");
  });

  it("falls back to default for empty/undefined", () => {
    expect(activeAnthropicModel(undefined)).toBe(ANTHROPIC_DEFAULT);
    expect(activeAnthropicModel("")).toBe(ANTHROPIC_DEFAULT);
  });
});
