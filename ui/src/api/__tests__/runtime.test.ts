import { describe, it, expect } from "vitest";
import { apiBaseUrl, rustApiBaseUrl, wsUrl, rustWsUrl } from "../runtime";

describe("runtime URLs", () => {
  it("apiBaseUrl defaults to Python on :3005", () => {
    expect(apiBaseUrl).toBe("http://127.0.0.1:3005");
  });

  it("rustApiBaseUrl defaults to Rust on :3006", () => {
    expect(rustApiBaseUrl).toBe("http://127.0.0.1:3006");
  });

  it("wsUrl (legacy) points at Python :3005", () => {
    expect(wsUrl).toBe("ws://127.0.0.1:3005/ws");
  });

  it("rustWsUrl defaults to Rust :3006", () => {
    expect(rustWsUrl).toBe("ws://127.0.0.1:3006/ws");
  });
});
