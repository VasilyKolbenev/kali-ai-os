import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { listen, invoke } = vi.hoisted(() => ({
  listen: vi.fn(),
  invoke: vi.fn(),
}));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

import { RECONCILE_MS, useStartupState } from "../useStartupState";

let handler: ((e: { payload: string }) => void) | undefined;
let unlisten: ReturnType<typeof vi.fn>;

beforeEach(() => {
  listen.mockReset();
  invoke.mockReset();
  handler = undefined;
  unlisten = vi.fn();
  listen.mockImplementation((_e: string, h: (e: { payload: string }) => void) => {
    handler = h;
    return Promise.resolve(unlisten);
  });
  invoke.mockResolvedValue("python_starting");
});
afterEach(() => vi.useRealTimers());

describe("useStartupState", () => {
  it("подписывается ДО invoke (переход не теряется)", async () => {
    const order: string[] = [];
    listen.mockImplementation((_e: string, h: (e: { payload: string }) => void) => {
      order.push("listen");
      handler = h;
      return Promise.resolve(unlisten);
    });
    invoke.mockImplementation(async () => {
      order.push("invoke");
      return "python_starting";
    });
    renderHook(() => useStartupState());
    await waitFor(() => expect(order).toContain("invoke"));
    expect(order[0]).toBe("listen");
  });

  it("пиннит точные строки event и command", async () => {
    renderHook(() => useStartupState());
    await waitFor(() => expect(invoke).toHaveBeenCalled());
    expect(listen).toHaveBeenCalledWith("startup://state", expect.any(Function));
    expect(invoke).toHaveBeenCalledWith("get_startup_state");
  });

  it("событие обновляет label", async () => {
    const { result } = renderHook(() => useStartupState());
    await waitFor(() => expect(handler).toBeTypeOf("function"));
    act(() => handler!({ payload: "degraded:crashed" }));
    await waitFor(() => expect(result.current).toBe("degraded:crashed"));
  });

  it("событие во время in-flight invoke побеждает (устаревший ответ отбрасывается)", async () => {
    vi.useFakeTimers();
    let resolveInvoke!: (v: string) => void;
    invoke.mockImplementation(() => new Promise<string>((r) => { resolveInvoke = r; }));
    const { result } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    act(() => handler!({ payload: "failed:rust_startup" }));
    await act(async () => { resolveInvoke("python_starting"); });
    expect(result.current).toBe("failed:rust_startup");
  });

  it("незавершённый listen() полностью блокирует invoke", async () => {
    vi.useFakeTimers();
    listen.mockImplementation((_e: string, h: (e: { payload: string }) => void) => {
      handler = h;
      return new Promise<never>(() => {});
    });
    renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS * 3 + 10); });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("отклонённый listen() уходит в polling-fallback без unhandled rejection", async () => {
    vi.useFakeTimers();
    const onUnhandled = vi.fn();
    process.on("unhandledRejection", onUnhandled);
    listen.mockImplementation(() => Promise.reject(new Error("no ipc")));
    invoke.mockResolvedValue("failed:gave_up");
    const { result } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS + 10); });
    expect(invoke).toHaveBeenCalled();
    expect(result.current).toBe("failed:gave_up");
    expect(onUnhandled).not.toHaveBeenCalled();
    process.off("unhandledRejection", onUnhandled);
  });

  it("late-listener self-heal: первый invoke падает, poll восстанавливает", async () => {
    vi.useFakeTimers();
    invoke.mockRejectedValueOnce(new Error("ipc not ready")).mockResolvedValue("python_ready");
    const { result } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS + 10); });
    expect(result.current).toBe("python_ready");
  });

  it("нет перекрывающихся invoke: медленный reconcile не переоткрывается", async () => {
    vi.useFakeTimers();
    let resolve!: (v: string) => void;
    invoke.mockImplementation(() => new Promise<string>((r) => { resolve = r; }));
    renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS * 3 + 10); });
    expect(invoke).toHaveBeenCalledTimes(1);
    await act(async () => { resolve("python_ready"); });
  });

  it("cleanup при unmount: unlisten вызван, интервал остановлен", async () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    unmount();
    expect(unlisten).toHaveBeenCalledTimes(1);
    const callsAfter = invoke.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS * 3 + 10); });
    expect(invoke.mock.calls.length).toBe(callsAfter);
  });

  it("unmount ВО ВРЕМЯ await listen() всё равно снимает подписку (без утечки)", async () => {
    let resolveListen!: (u: () => void) => void;
    listen.mockImplementation((_e: string, h: (e: { payload: string }) => void) => {
      handler = h;
      return new Promise<() => void>((r) => { resolveListen = r; });
    });
    const { unmount } = renderHook(() => useStartupState());
    unmount();
    await act(async () => { resolveListen(unlisten); });
    expect(unlisten).toHaveBeenCalledTimes(1);
  });
});
