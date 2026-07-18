# A3 Commit 4 — Honest Boot & Degraded Surface Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop UI reflect the authoritative Rust startup-state — an infinite onboarding splash must yield to an honest degraded/failed surface, and terminal failure must be decided only by Rust, never by a JS timer.

**Architecture:** The UI consumes the Tauri IPC startup contract for the first time: `useStartupState` subscribes to the `startup://state` event *before* calling the `get_startup_state` command (no missed transition), starts its reconciliation poll only after `listen()` settles, treats events as authoritative over in-flight reads, and cleans up on unmount. A pure `classifyStartup(label)` maps the raw label to a view kind (`booting`/`ready`/`degraded`/`failed`) plus RU copy. `App.tsx` reads that classification *before* the onboarding early-return so degraded/failed overlays win over the boot splash and the wizard. The old timer-driven terminal branch (`useKernelStage` stage 2) is removed.

**Tech Stack:** React 19 + TypeScript, Zustand, `@tauri-apps/api@^2` (event `listen`, core `invoke`), Vitest + Testing Library.

---

## Rust contract (authoritative — do NOT change in this commit)

`get_startup_state(app) -> String` (command, `src-tauri/src/lib.rs:176`) and event `startup://state` (`STARTUP_EVENT`, `lib.rs:27`) both carry the same **label string** (`state_label`, `lib.rs:154`). The command fixes first-paint on first call. Emitted labels and their **UI routing** (owner-decided — note that two `degraded:` wire labels are surfaced as terminal red, because they need user action and the supervisor cannot recover them on its own):

| Label | UI kind | Copy reason |
|---|---|---|
| `shell_ready` | booting | — |
| `rust_ready` | booting | — |
| `python_starting` | booting | — |
| `python_ready` | ready | — |
| `degraded:not_found` | **failed (red)** | `not_found` |
| `degraded:port_occupied` | **failed (red)** | `port_occupied` |
| `degraded:crashed` | degraded (amber) | `crashed` |
| `degraded:foreign_backend` | degraded (amber) | `foreign_backend` |
| `degraded:spawn_failed` | degraded (amber) | `spawn_failed` |
| `degraded:process_unknown` | degraded (amber) | `process_unknown` |
| `failed:rust_startup` | failed (red) | `rust_startup` |
| `failed:gave_up` | failed (red) | `gave_up` |
| `failed` | failed (red) | `generic` → `failed_generic` copy |
| *(any other non-null label)* | **failed (red)** | `protocol_error` |

**Rules:**
- `null` (before the first read) and the three booting labels → `booting`: keep the existing splash, no overlay.
- Any **unknown non-null** label → `failed` / `protocol_error`. The UI does not understand the protocol, so it says so honestly rather than hiding a possibly-broken app behind a splash.
- `degraded_generic` / `failed_generic` are **copy-lookup fallbacks by kind** (used if a routed reason has no own entry), not routing outcomes.

---

## File Structure

- **Create** `ui/src/lib/startupState.ts` — pure `classifyStartup(label: string | null): StartupView` + RU copy map keyed by reason. No React, no IPC → trivially unit-testable.
- **Create** `ui/src/hooks/useStartupState.ts` — the IPC hook. Returns the raw label (`string | null`). Owns subscribe-before-invoke ordering, listen-settlement-gated polling, event-authoritative reconciliation, cleanup. Exports `RECONCILE_MS`, `STARTUP_EVENT`.
- **Create** `ui/src/components/Startup/StartupSurface.tsx` — presentational overlay for `degraded`/`failed` (returns `null` for `booting`/`ready`).
- **Modify** `ui/src/App.tsx` — call `useStartupState()` + `classifyStartup`; render `StartupSurface` with priority **before** the onboarding early-return; remove the `kernelStage === 2` timer-terminal branch and the `failMs` timer.
- **Modify** `ui/package.json` + `ui/pnpm-lock.yaml` — add `@tauri-apps/api@^2` as a direct dependency (these two files only).
- **Test** `ui/src/lib/__tests__/startupState.test.ts`, `ui/src/hooks/__tests__/useStartupState.test.ts`, `ui/src/__tests__/App.startup.test.tsx`.

**Boundaries (do NOT touch):** OPUS-102 / model-loading, `updater.rs` / OPUS-202, voice models, the Rust startup contract, any non-`ui/` file except this plan. No behavior change to `useOnboardingGate`.

---

## Chunk 1: Dependency

### Task 1: Add `@tauri-apps/api@^2` as a direct dependency

**Files:**
- Modify: `ui/package.json`
- Modify: `ui/pnpm-lock.yaml`

- [ ] **Step 1: Add the dependency**

`@tauri-apps/cli` (build tool) does NOT depend on `@tauri-apps/api` (JS runtime bindings), so expect a network fetch. Run from the repo root (no `cd`):

```bash
pnpm --dir ui add "@tauri-apps/api@^2"
```

- [ ] **Step 2: Verify only the two intended files changed**

```bash
git status --short ui/
```
Expected: exactly `ui/package.json` and `ui/pnpm-lock.yaml` modified, nothing else. `@tauri-apps/api` sits under `dependencies` (not `devDependencies`) at `^2`.

- [ ] **Step 3: Commit**

```bash
git add ui/package.json ui/pnpm-lock.yaml
git commit -m "build(ui): add @tauri-apps/api for startup IPC"
```

---

## Chunk 2: Pure classifier (`startupState.ts`)

### Task 2: `classifyStartup` — label → view

**Files:**
- Create: `ui/src/lib/startupState.ts`
- Test: `ui/src/lib/__tests__/startupState.test.ts`

Tests assert **routing** (kind + reason), which the classifier controls, plus **structural** copy invariants (every overlay label yields distinct, non-placeholder copy). Wording is owner-approved; these invariants must survive any future wording edit.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest";
import { classifyStartup } from "../startupState";

/** Every contract label that must render an overlay, with its required kind. */
const OVERLAY: ReadonlyArray<[label: string, kind: "failed" | "degraded", reason: string]> = [
  ["degraded:not_found", "failed", "not_found"],
  ["degraded:port_occupied", "failed", "port_occupied"],
  ["degraded:crashed", "degraded", "crashed"],
  ["degraded:foreign_backend", "degraded", "foreign_backend"],
  ["degraded:spawn_failed", "degraded", "spawn_failed"],
  ["degraded:process_unknown", "degraded", "process_unknown"],
  ["failed:rust_startup", "failed", "rust_startup"],
  ["failed:gave_up", "failed", "gave_up"],
  ["failed", "failed", "generic"],
];

const FORBIDDEN_PLACEHOLDER = /TODO|PENDING|PLACEHOLDER/i;

describe("classifyStartup", () => {
  it("null and booting labels → booting (no overlay)", () => {
    for (const l of [null, "shell_ready", "rust_ready", "python_starting"]) {
      expect(classifyStartup(l).kind).toBe("booting");
    }
  });

  it("python_ready → ready", () => {
    expect(classifyStartup("python_ready").kind).toBe("ready");
  });

  it.each(OVERLAY)("%s routes to %s/%s", (label, kind, reason) => {
    const v = classifyStartup(label);
    expect(v.kind).toBe(kind);
    expect(v.reason).toBe(reason);
  });

  it("not_found and port_occupied are RED despite the degraded: wire prefix", () => {
    expect(classifyStartup("degraded:not_found").kind).toBe("failed");
    expect(classifyStartup("degraded:port_occupied").kind).toBe("failed");
  });

  it("unknown non-null label → failed/protocol_error (never booting)", () => {
    for (const l of ["wat:nonsense", "degraded:brand_new", "python_starting_v2", ""]) {
      const v = classifyStartup(l);
      expect(v.kind).toBe("failed");
      expect(v.reason).toBe("protocol_error");
    }
  });

  it("every overlay label yields distinct, real copy", () => {
    const views = [...OVERLAY.map(([l]) => classifyStartup(l)),
                   classifyStartup("wat:unknown")]; // + protocol_error
    const keys = new Set(views.map((v) => `${v.title}|${v.body}`));
    expect(keys.size).toBe(views.length);          // all distinct
    for (const v of views) {
      expect(v.title.trim().length).toBeGreaterThan(0);
      expect(v.body.trim().length).toBeGreaterThan(0);
      expect(v.title.trim()).not.toBe("…");        // bare ellipsis = unfilled slot
      expect(v.body.trim()).not.toBe("…");
      expect(v.title).not.toMatch(FORBIDDEN_PLACEHOLDER);
      expect(v.body).not.toMatch(FORBIDDEN_PLACEHOLDER);
    }
  });

  it("booting/ready carry no copy", () => {
    expect(classifyStartup("python_ready").title).toBe("");
    expect(classifyStartup(null).title).toBe("");
  });
});
```

*(Natural mid-sentence ellipsis inside real copy is allowed; only a string that IS just `…`, or one containing TODO/PENDING/PLACEHOLDER, counts as unfilled.)*

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm --dir ui vitest run src/lib/__tests__/startupState.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```ts
// ui/src/lib/startupState.ts
export type StartupKind = "booting" | "ready" | "degraded" | "failed";

export interface StartupView {
  kind: StartupKind;
  /** stable slug: "not_found" | "crashed" | … | "generic" | "protocol_error" */
  reason: string;
  title: string;
  body: string;
}

const BOOTING = new Set(["shell_ready", "rust_ready", "python_starting"]);

/** Terminal (red): needs user action — the supervisor cannot recover these. */
const RED = new Set([
  "failed",
  "failed:rust_startup",
  "failed:gave_up",
  "degraded:not_found",
  "degraded:port_occupied",
]);

/** Recoverable (amber): the supervisor is actively retrying. */
const AMBER = new Set([
  "degraded:crashed",
  "degraded:foreign_backend",
  "degraded:spawn_failed",
  "degraded:process_unknown",
]);

// RU copy — owner-approved 2026-07-18.
const COPY: Record<string, { title: string; body: string }> = {
  not_found: {
    title: "Компонент KALI не найден",
    body: "Один из файлов приложения отсутствует. Переустанови KALI и запусти приложение снова.",
  },
  crashed: {
    title: "Ядро перезапускается",
    body: "Локальный сервис неожиданно остановился. KALI автоматически запускает его снова.",
  },
  port_occupied: {
    title: "Локальный сервис занят",
    body: "Закрой другую копию KALI и перезапусти приложение. Если ошибка повторится, перезагрузи компьютер.",
  },
  foreign_backend: {
    title: "Обнаружена другая копия ядра",
    body: "Закрой другие процессы KALI. После этого восстановление продолжится автоматически.",
  },
  spawn_failed: {
    title: "Повторяю запуск ядра",
    body: "Первая попытка не удалась. KALI повторит запуск автоматически.",
  },
  process_unknown: {
    title: "Проверяю состояние ядра",
    body: "KALI временно не может подтвердить состояние локального процесса и повторяет проверку.",
  },
  degraded_generic: {
    title: "Восстанавливаю ядро",
    body: "KALI обнаружила временную проблему и пытается восстановить работу автоматически.",
  },
  rust_startup: {
    title: "Не удалось запустить локальный сервис",
    body: "Перезапусти KALI. Если ошибка повторится, передай разработчику логи из папки %APPDATA%\\KALI\\logs.",
  },
  gave_up: {
    title: "Ядро не удалось восстановить",
    body: "Автоматические попытки завершены. Перезапусти KALI; если ошибка повторится, передай диагностические логи.",
  },
  failed_generic: {
    title: "Не удалось завершить запуск KALI",
    body: "Перезапусти приложение. Если ошибка повторится, передай диагностические логи.",
  },
  protocol_error: {
    title: "Не удалось определить состояние запуска",
    body: "Перезапусти KALI. Если ошибка повторится, передай диагностические логи.",
  },
};

/** Copy lookup with a by-kind defensive fallback (never returns undefined). */
function copyFor(reason: string, kind: "failed" | "degraded") {
  return COPY[reason] ?? (kind === "failed" ? COPY.failed_generic : COPY.degraded_generic);
}

export function classifyStartup(label: string | null): StartupView {
  if (label === null || BOOTING.has(label)) {
    return { kind: "booting", reason: "booting", title: "", body: "" };
  }
  if (label === "python_ready") {
    return { kind: "ready", reason: "ready", title: "", body: "" };
  }
  if (RED.has(label)) {
    const reason = label === "failed" ? "generic" : label.slice(label.indexOf(":") + 1);
    return { kind: "failed", reason, ...copyFor(reason, "failed") };
  }
  if (AMBER.has(label)) {
    const reason = label.slice(label.indexOf(":") + 1);
    return { kind: "degraded", reason, ...copyFor(reason, "degraded") };
  }
  // Unknown non-null label: be honest rather than hide a broken app.
  return { kind: "failed", reason: "protocol_error", ...COPY.protocol_error };
}
```

- [ ] **Step 4: Run to verify pass**

Run: `pnpm --dir ui vitest run src/lib/__tests__/startupState.test.ts`
Expected: PASS.

- [ ] **Step 5: Mutation checks**

1. Move `"degraded:not_found"` from `RED` to `AMBER` → the "RED despite degraded: prefix" test goes red. Revert.
2. Change the unknown-label return to `kind: "booting"` → the protocol_error test goes red. Revert.

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/startupState.ts ui/src/lib/__tests__/startupState.test.ts
git commit -m "feat(ui): pure startup-state classifier with approved RU copy"
```

---

## Chunk 3: IPC hook (`useStartupState.ts`)

### Task 3: `useStartupState` — settlement-gated polling, event-authoritative

**Files:**
- Create: `ui/src/hooks/useStartupState.ts`
- Test: `ui/src/hooks/__tests__/useStartupState.test.ts`

**Ordering contract:**
1. `listen()` is called first; **no `invoke` may happen until `listen()` settles.**
2. On **resolve** → one initial `reconcile()`, then start the interval.
3. On **reject** → controlled polling fallback (initial `reconcile()` + interval), no unhandled rejection.
4. Events are authoritative: an `invoke` result is discarded if any event arrived while it was in flight.

**Mocking note:** mock `@tauri-apps/api/event` (`listen`) and `@tauri-apps/api/core` (`invoke`). Declare the spies with `vi.hoisted` so they exist when the hoisted `vi.mock` factory runs.

- [ ] **Step 1: Write the failing tests (10 tests)**

```ts
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
  it("subscribes BEFORE invoking (no missed transition)", async () => {
    const order: string[] = [];
    listen.mockImplementation((_e, h) => { order.push("listen"); handler = h; return Promise.resolve(unlisten); });
    invoke.mockImplementation(async () => { order.push("invoke"); return "python_starting"; });
    renderHook(() => useStartupState());
    await waitFor(() => expect(order).toContain("invoke"));
    expect(order[0]).toBe("listen");
  });

  it("pins the exact event name and command string", async () => {
    renderHook(() => useStartupState());
    await waitFor(() => expect(invoke).toHaveBeenCalled());
    expect(listen).toHaveBeenCalledWith("startup://state", expect.any(Function));
    expect(invoke).toHaveBeenCalledWith("get_startup_state");
  });

  it("an event updates the label", async () => {
    const { result } = renderHook(() => useStartupState());
    await waitFor(() => expect(handler).toBeTypeOf("function"));
    act(() => handler!({ payload: "degraded:crashed" }));
    await waitFor(() => expect(result.current).toBe("degraded:crashed"));
  });

  it("an event during an in-flight invoke wins (stale read discarded)", async () => {
    vi.useFakeTimers();
    let resolveInvoke!: (v: string) => void;
    invoke.mockImplementation(() => new Promise<string>((r) => { resolveInvoke = r; }));
    const { result } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    act(() => handler!({ payload: "failed:rust_startup" }));
    await act(async () => { resolveInvoke("python_starting"); });
    expect(result.current).toBe("failed:rust_startup");
  });

  it("an unresolved listen() blocks invoke entirely", async () => {
    vi.useFakeTimers();
    listen.mockImplementation((_e, h) => { handler = h; return new Promise<never>(() => {}); });
    renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS * 3 + 10); });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("a rejected listen() falls back to polling without unhandled rejection", async () => {
    vi.useFakeTimers();
    const onUnhandled = vi.fn();
    process.on("unhandledRejection", onUnhandled);
    listen.mockImplementation(() => Promise.reject(new Error("no ipc")));
    invoke.mockResolvedValue("failed:gave_up");
    const { result } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS + 10); });
    expect(invoke).toHaveBeenCalled();                 // fallback polling ran
    expect(result.current).toBe("failed:gave_up");
    expect(onUnhandled).not.toHaveBeenCalled();
    process.off("unhandledRejection", onUnhandled);
  });

  it("late-listener self-heal: initial invoke rejects, the poll recovers", async () => {
    vi.useFakeTimers();
    invoke.mockRejectedValueOnce(new Error("ipc not ready")).mockResolvedValue("python_ready");
    const { result } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS + 10); });
    expect(result.current).toBe("python_ready");
  });

  it("no overlapping invoke: a slow reconcile is not re-entered", async () => {
    vi.useFakeTimers();
    let resolve!: (v: string) => void;
    invoke.mockImplementation(() => new Promise<string>((r) => { resolve = r; }));
    renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS * 3 + 10); });
    expect(invoke).toHaveBeenCalledTimes(1);
    await act(async () => { resolve("python_ready"); });
  });

  it("cleanup on unmount: unlisten called, interval stopped", async () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useStartupState());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    unmount();
    expect(unlisten).toHaveBeenCalledTimes(1);
    const callsAfter = invoke.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(RECONCILE_MS * 3 + 10); });
    expect(invoke.mock.calls.length).toBe(callsAfter);
  });

  it("unmount DURING the listen() await still unlistens (no leak)", async () => {
    let resolveListen!: (u: () => void) => void;
    listen.mockImplementation((_e, h) => { handler = h; return new Promise((r) => { resolveListen = r; }); });
    const { unmount } = renderHook(() => useStartupState());
    unmount();
    await act(async () => { resolveListen(unlisten); });
    expect(unlisten).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm --dir ui vitest run src/hooks/__tests__/useStartupState.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```ts
// ui/src/hooks/useStartupState.ts
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

export const STARTUP_EVENT = "startup://state";
export const RECONCILE_MS = 2000;

/** Authoritative Rust startup label (`state_label`), or null before the first read. */
export function useStartupState(): string | null {
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    let polling = false;
    let eventSeq = 0;                       // bumped on every live event
    let intervalId: ReturnType<typeof setInterval> | undefined;

    const reconcile = async () => {
      if (polling || cancelled) return;    // no overlapping invoke
      polling = true;
      const seqAtDispatch = eventSeq;       // event epoch at read time
      try {
        const cur = await invoke<string>("get_startup_state");
        // Events are authoritative: if one arrived while this read was in
        // flight, its value is fresher — drop the (possibly stale) result.
        if (!cancelled && eventSeq === seqAtDispatch) setLabel(cur);
      } catch {
        /* Rust IPC not ready yet — keep last; the next poll retries. */
      } finally {
        polling = false;
      }
    };

    /** Initial read + periodic self-heal. Only ever called after listen settles. */
    const startPolling = () => {
      if (cancelled || intervalId !== undefined) return;
      void reconcile();
      intervalId = setInterval(() => { void reconcile(); }, RECONCILE_MS);
    };

    // Subscribe FIRST; no invoke may happen until this settles, so no
    // transition can slip between the read and the subscription.
    listen<string>(STARTUP_EVENT, (e) => {
      if (cancelled) return;
      eventSeq += 1;
      setLabel(e.payload);
    }).then(
      (un) => {
        if (cancelled) { un(); return; }   // unmounted mid-await → unlisten now
        unlisten = un;
        startPolling();
      },
      () => {
        // listen unavailable → controlled polling fallback (handled here, so
        // the rejection never escapes as an unhandled rejection).
        startPolling();
      },
    );

    return () => {
      cancelled = true;
      if (intervalId !== undefined) clearInterval(intervalId);
      if (unlisten) unlisten();
    };
  }, []);

  return label;
}
```

> **Self-heal bound:** the poll's self-heal depends on `invoke` settling (`polling` clears only in `finally`). The Rust `get_startup_state` command is synchronous and cheap, so a permanent hang is not expected; events keep flowing regardless. Documented dependency, not a guard (YAGNI).

- [ ] **Step 4: Run to verify pass**

Run: `pnpm --dir ui vitest run src/hooks/__tests__/useStartupState.test.ts`
Expected: PASS — 10 tests.

- [ ] **Step 5: Mutation checks**

1. Remove the `if (polling ...) return;` guard → "no overlapping invoke" goes red. Revert.
2. Call `startPolling()` before `listen(...)` instead of in its settle handlers → "unresolved listen() blocks invoke" goes red. Revert.
3. Drop the rejection handler (second `then` arg) → "rejected listen() falls back to polling" goes red. Revert.
4. Drop the `eventSeq === seqAtDispatch` check → "event during an in-flight invoke wins" goes red. Revert.
5. Drop `if (unlisten) unlisten()` from cleanup → "cleanup on unmount" goes red. Revert.

- [ ] **Step 6: Commit**

```bash
git add ui/src/hooks/useStartupState.ts ui/src/hooks/__tests__/useStartupState.test.ts
git commit -m "feat(ui): startup-state IPC hook (settlement-gated poll, event-authoritative)"
```

---

## Chunk 4: Surface component + App wiring

### Task 4: `StartupSurface` presentational overlay

**Files:**
- Create: `ui/src/components/Startup/StartupSurface.tsx`

- [ ] **Step 1: Implement (pure presentational)**

```tsx
// ui/src/components/Startup/StartupSurface.tsx
import type { StartupView } from "../../lib/startupState";

/** Renders an overlay ONLY for degraded (amber) / failed (red); else null. */
export function StartupSurface({ view }: { view: StartupView }) {
  if (view.kind !== "degraded" && view.kind !== "failed") return null;
  const failed = view.kind === "failed";
  const color = failed ? "var(--j-red, #ef4444)" : "var(--j-amber, #f59e0b)";
  return (
    <div
      role="alert"
      data-testid={`startup-${view.kind}`}
      className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 text-center px-8"
      style={{ background: "var(--j-bg)", color: "var(--j-text-dim)" }}
    >
      <div className="text-lg font-semibold" style={{ color }}>{view.title}</div>
      <div className="text-sm max-w-md" style={{ color: "var(--j-text-muted)" }}>{view.body}</div>
    </div>
  );
}
```

Committed together with Task 5 (App wiring makes it observable).

### Task 5: Wire `App.tsx` — priority over onboarding; remove the timer-terminal

**Files:**
- Modify: `ui/src/App.tsx`
- Test: `ui/src/__tests__/App.startup.test.tsx`

- [ ] **Step 1: Write the failing App tests (U1–U5)**

Spies via `vi.hoisted` (the `vi.mock` factories are hoisted above module init) and the current `vi.fn<() => T>` generic form.

```tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { startupLabel, gate } = vi.hoisted(() => ({
  startupLabel: vi.fn<() => string | null>(),
  gate: vi.fn<() => { loading: boolean; gated: boolean; slow: boolean }>(),
}));

vi.mock("../hooks/useStartupState", () => ({ useStartupState: () => startupLabel() }));
vi.mock("../hooks/useOnboardingGate", () => ({ useOnboardingGate: () => gate() }));
vi.mock("../api/websocket", () => ({ useWebSocket: () => {} }));
// Keep the render shallow — stub heavy children/stores as the existing suites do.

import App from "../App";

describe("App startup surface", () => {
  beforeEach(() => {
    startupLabel.mockReturnValue(null);
    gate.mockReturnValue({ loading: true, gated: true, slow: false });
  });

  it("U1: amber degraded overrides the infinite onboarding splash", () => {
    startupLabel.mockReturnValue("degraded:crashed");
    render(<App />);
    expect(screen.getByTestId("startup-degraded")).toBeInTheDocument();
    expect(screen.queryByText(/Джарвис запускается/)).not.toBeInTheDocument();
  });

  it("U2: failed overrides the onboarding wizard", () => {
    startupLabel.mockReturnValue("failed:rust_startup");
    gate.mockReturnValue({ loading: false, gated: true, slow: false });
    render(<App />);
    expect(screen.getByTestId("startup-failed")).toBeInTheDocument();
  });

  it("U3: booting keeps the boot splash (overlay separate from model-loading)", () => {
    startupLabel.mockReturnValue("python_starting");
    render(<App />);
    expect(screen.getByText(/Джарвис запускается/)).toBeInTheDocument();
    expect(screen.queryByTestId("startup-degraded")).not.toBeInTheDocument();
    expect(screen.queryByTestId("startup-failed")).not.toBeInTheDocument();
  });

  it("U4: degraded:not_found renders RED, not amber", () => {
    startupLabel.mockReturnValue("degraded:not_found");
    render(<App />);
    expect(screen.getByTestId("startup-failed")).toBeInTheDocument();
    expect(screen.queryByTestId("startup-degraded")).not.toBeInTheDocument();
  });

  it("U5: an unknown label renders the red protocol-error surface", () => {
    startupLabel.mockReturnValue("wat:nonsense");
    render(<App />);
    expect(screen.getByTestId("startup-failed")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm --dir ui vitest run src/__tests__/App.startup.test.tsx`
Expected: FAIL — no `startup-*` testid.

- [ ] **Step 3: Modify `App.tsx`**

Among the existing top-of-component hooks (keeps hook order stable):
```tsx
const startupLabel = useStartupState();
const startup = classifyStartup(startupLabel);
```
Then, **after all hooks** and **before** the `if (onboardingLoading)` early-return:
```tsx
// Rust startup-state is authoritative: a failed/degraded backend must win
// over both the boot splash and the onboarding wizard.
if (startup.kind === "failed" || startup.kind === "degraded") {
  return <StartupSurface view={startup} />;
}
```
Remove the timer-terminal: delete the `kernelStage === 2` red branch and drop `failMs` plus its `setTimeout` from `useKernelStage`, so it can no longer manufacture a terminal state (it becomes `0 | 1`, transient reconnect only). Terminal is now solely `startup.kind === "failed"`. Add imports for `useStartupState`, `classifyStartup`, `StartupSurface`.

- [ ] **Step 4: Run to verify pass**

Run: `pnpm --dir ui vitest run src/__tests__/App.startup.test.tsx`
Expected: PASS — U1–U5.

- [ ] **Step 5: Full UI gate**

Run: `pnpm --dir ui vitest run` and `pnpm --dir ui tsc -b --noEmit`
Expected: all suites pass, no type errors. Confirm no other test depended on `kernelStage === 2`.

- [ ] **Step 6: Commit**

```bash
git add ui/src/App.tsx ui/src/components/Startup/StartupSurface.tsx ui/src/__tests__/App.startup.test.tsx
git commit -m "feat(ui): honest boot and degraded surface over onboarding"
```

---

## Verification & gates (definition of done)

- `pnpm --dir ui vitest run` — all suites green (new: `startupState`, `useStartupState` ×10, `App.startup` ×5).
- `pnpm --dir ui tsc -b --noEmit` — no type errors.
- Mutation evidence recorded for classifier (2) and hook (5).
- `git status ui/` — only intended files touched; no OPUS-102 / updater / model files.
- **⛔ STOP before the GUI live gate.** GUI live evidence (Vasily's desktop) is a separate gate: each red/amber surface renders over the boot splash for its real trigger; healthy `python_ready` shows the normal UI; a degraded→`python_ready` recovery clears the overlay via reconciliation.

## Non-goals / deferrals

- No change to the Rust contract, `useOnboardingGate`, model-loading (OPUS-102), updater (OPUS-202), or voice models.
- The transient WS "reconnecting" hint (`kernelStage === 1`) stays as a non-terminal amber banner; only its terminal (`=== 2`) role is removed.
- **Trade-off:** with the timer-terminal gone, a backend that is `python_ready` per Rust's HTTP `/health` probe but whose UI WebSocket is wedged no longer escalates to a red "restart" banner — it rests on the amber `kernelStage === 1` hint (whose copy already says to restart if it persists). Rust startup-state, not WS liveness, owns terminal. Accepted for A3.
