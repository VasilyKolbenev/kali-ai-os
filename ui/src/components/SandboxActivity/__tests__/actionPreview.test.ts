import { describe, it, expect } from "vitest";
import { parseActionPreview } from "../actionPreview";

describe("parseActionPreview", () => {
  it("extracts label and risk from a valid audit extra payload", () => {
    const extra = JSON.stringify({
      preview_label: "Отправит письмо от твоего имени",
      preview_risk: "high",
    });
    expect(parseActionPreview(extra)).toEqual({
      label: "Отправит письмо от твоего имени",
      risk: "high",
    });
  });

  it("returns null for null extra", () => {
    expect(parseActionPreview(null)).toBeNull();
  });

  it("returns null for malformed JSON", () => {
    expect(parseActionPreview("{not json")).toBeNull();
  });

  it("returns null when preview fields are absent", () => {
    expect(parseActionPreview(JSON.stringify({ other: 1 }))).toBeNull();
  });

  it("returns null for an invalid risk tier", () => {
    const extra = JSON.stringify({ preview_label: "x", preview_risk: "bogus" });
    expect(parseActionPreview(extra)).toBeNull();
  });
});
