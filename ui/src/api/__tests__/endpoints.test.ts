import { describe, it, expect } from "vitest";
import { resolveApiUrl, RUST_ENDPOINTS } from "../endpoints";

describe("endpoint dispatcher", () => {
  it("routes RUST_ENDPOINTS paths to the Rust backend", () => {
    for (const path of RUST_ENDPOINTS) {
      const url = resolveApiUrl(path);
      expect(url).toContain(":3006");
    }
  });

  it("routes unmigrated paths to Python", () => {
    const url = resolveApiUrl("/skills");
    expect(url).toContain(":3005");
  });

  it("is stable on query strings and trailing slashes", () => {
    expect(resolveApiUrl("/config?reload=1")).toContain(":3006");
    expect(resolveApiUrl("/skills/")).toContain(":3005");
  });
});
