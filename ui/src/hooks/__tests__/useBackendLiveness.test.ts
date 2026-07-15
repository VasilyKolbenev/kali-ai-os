import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CRASH_POLL_MS, useBackendLiveness } from "../useBackendLiveness";

function reply(alive: boolean) {
  return new Response(JSON.stringify({ backend_alive: alive }));
}

describe("useBackendLiveness", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("не сообщает down, пока стрик не набран", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(false)));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CRASH_POLL_MS + 10); // 2 пробы (mount + 1)
    });
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });

  it("сообщает down после 3 подряд", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(false)));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 3 + 10);
    });
    expect(result.current).toBe(true);
    vi.useRealTimers();
  });

  it("любой alive сбрасывает стрик", async () => {
    let n = 0;
    // Тиков будет 5 (mount + 4 интервала): down, down, UP, down, down
    // → максимум 2 подряд, порог 3 не достигнут.
    // ВНИМАНИЕ: не увеличивать окно — 6-й тик clamp'нется на последний
    // `false` и сфабрикует 3-й подряд down, тест станет ложно-красным.
    const seq = [false, false, true, false, false];
    vi.stubGlobal("fetch", vi.fn(async () => reply(seq[Math.min(n++, seq.length - 1)])));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 4 + 10);
    });
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });

  it("unmount останавливает поллинг — интервал не течёт", async () => {
    const fetchMock = vi.fn(async () => reply(true));
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useBackendLiveness());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 2 + 10);
    });
    const callsAtUnmount = fetchMock.mock.calls.length;
    expect(callsAtUnmount).toBeGreaterThan(1); // поллинг реально шёл до unmount
    unmount();
    await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 5 + 10);
    expect(fetchMock.mock.calls.length).toBe(callsAtUnmount);
    vi.useRealTimers();
  });

  it("недоступный :3006 (reject) НЕ показывает down — Rust мёртв, вне скоупа", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("refused"); }));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 4 + 10);
    });
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});
