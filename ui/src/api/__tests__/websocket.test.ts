import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("../client", () => ({
  api: { voiceStatus: vi.fn().mockResolvedValue({ started: false, state: "idle" }) },
}));
vi.mock("../runtime", () => ({ rustWsUrl: "ws://test/ws" }));

import { useWebSocket } from "../websocket";

/** Minimal WebSocket stand-in: records instances and emulates onclose firing
    when close() is called (as a real browser does). */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: unknown) => void) | null = null;
  readyState = 0;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

describe("useWebSocket reconnect lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not reconnect after unmount (no zombie sockets)", () => {
    const { unmount } = renderHook(() => useWebSocket());
    expect(FakeWebSocket.instances).toHaveLength(1);

    unmount(); // cleanup → close() → onclose must NOT schedule a reconnect
    vi.advanceTimersByTime(5000);

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects while still mounted when the socket drops", () => {
    renderHook(() => useWebSocket());
    expect(FakeWebSocket.instances).toHaveLength(1);

    // Server dropped us (not an unmount) → a reconnect is expected.
    FakeWebSocket.instances[0].onclose?.();
    vi.advanceTimersByTime(3000);

    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
