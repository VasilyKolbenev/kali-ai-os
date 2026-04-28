import { describe, it, expect } from "vitest";
import { resolveApiUrl, RUST_ENDPOINTS } from "../endpoints";

describe("endpoint dispatcher", () => {
  it("routes every RUST_ENDPOINTS entry to the Rust backend for its declared method", () => {
    for (const { method, path } of RUST_ENDPOINTS) {
      expect(resolveApiUrl(path, method)).toContain(":3006");
    }
  });

  it("routes unmigrated paths to Python", () => {
    expect(resolveApiUrl("/skills")).toContain(":3005");
    expect(resolveApiUrl("/settings", "POST")).toContain(":3005");
  });

  it("routes an undeclared method to Python even if the path is in Rust for other methods", () => {
    // POST /config is NOT in the allow-list — must go to Python (which would 405,
    // but that's the correct downstream behaviour, not a dispatcher miss).
    expect(resolveApiUrl("/config", "POST")).toContain(":3005");
    // PATCH /voice/status is NOT declared (only GET is) — must go to Python.
    expect(resolveApiUrl("/voice/status", "PATCH")).toContain(":3005");
  });

  it("routes PATCH /config to Rust (Rust proxies to Python)", () => {
    expect(resolveApiUrl("/config", "PATCH")).toContain(":3006");
  });

  it("is stable on query strings and trailing slashes", () => {
    expect(resolveApiUrl("/config?reload=1")).toContain(":3006");
    expect(resolveApiUrl("/skills/")).toContain(":3005");
  });

  it("defaults method to GET when omitted", () => {
    expect(resolveApiUrl("/health")).toContain(":3006");
    expect(resolveApiUrl("/skills")).toContain(":3005");
  });

  it("dispatches path-param children of a prefix entry to Rust", () => {
    // /catalog/pack is registered with prefix:true so any /catalog/pack/<name>
    // routes to the Rust dispatcher (which then proxies to Python).
    expect(resolveApiUrl("/catalog/pack/weather", "POST")).toContain(":3006");
    expect(resolveApiUrl("/catalog/pack/строитель-помощник", "POST")).toContain(":3006");
  });

  it("does not let a prefix bleed into a longer sibling path", () => {
    // /catalog/packed must NOT match the /catalog/pack prefix entry —
    // we want true segment boundaries, not raw startsWith collisions.
    expect(resolveApiUrl("/catalog/packed", "POST")).toContain(":3005");
    expect(resolveApiUrl("/catalog/pack-foo", "POST")).toContain(":3005");
  });
});
