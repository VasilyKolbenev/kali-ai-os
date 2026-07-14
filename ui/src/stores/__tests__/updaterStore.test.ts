// ui/src/stores/__tests__/updaterStore.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stopPollForTests, useUpdaterStore } from "../updaterStore";

function snap(partial: Record<string, unknown> = {}) {
  return {
    phase: "idle", current: "1.0.0-rc1", available: null,
    total: 0, downloaded: 0, error: null, ...partial,
  };
}

describe("updaterStore", () => {
  beforeEach(() => {
    useUpdaterStore.setState(useUpdaterStore.getInitialState());
    stopPollForTests();       // упавший тест не должен утекать интервалом в следующий
    vi.unstubAllGlobals();    // restoreAllMocks НЕ снимает stubGlobal
  });

  it("check stores snapshot from POST /updater/check", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(
      snap({ phase: "available", available: { version: "1.0.1", notes: "n", assets: [], pub_date: "" }, total: 100 }),
    ))));
    await useUpdaterStore.getState().check();
    const s = useUpdaterStore.getState();
    expect(s.phase).toBe("available");
    expect(s.available?.version).toBe("1.0.1");
  });

  it("check failure is silent (stays idle, no error)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await useUpdaterStore.getState().check();
    const s = useUpdaterStore.getState();
    expect(s.phase).toBe("idle");
    expect(s.error).toBeNull();
  });

  it("download starts polling until terminal phase", async () => {
    vi.useFakeTimers();
    const phases = [
      snap({ phase: "downloading", total: 100, downloaded: 50 }),
      snap({ phase: "ready", total: 100, downloaded: 100 }),
    ];
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify(phases[Math.min(call++, phases.length - 1)]))));
    await useUpdaterStore.getState().download(); // POST → downloading
    expect(useUpdaterStore.getState().phase).toBe("downloading");
    await vi.advanceTimersByTimeAsync(800);      // первый poll → ready
    expect(useUpdaterStore.getState().phase).toBe("ready");
    await vi.advanceTimersByTimeAsync(2000);     // poll остановлен
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2);
    vi.useRealTimers();
  });

  it("dismiss hides banner until next available version", () => {
    useUpdaterStore.setState({ phase: "available" });
    useUpdaterStore.getState().dismiss();
    expect(useUpdaterStore.getState().dismissed).toBe(true);
  });
});
