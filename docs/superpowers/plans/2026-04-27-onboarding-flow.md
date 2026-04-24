# Onboarding Flow Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 5-step onboarding surface that converts a fresh KALI install into a working agent in ≤2 minutes without the user touching `.env`, terminal, or docs. Detection is automatic on first launch; the existing app surfaces are gated until onboarding completes (or is explicitly skipped). This is the **TIER 1 BLOCKER** for non-tech friend distribution — without it, every non-tech installer is an 80%-churn Day-1 loss.

**Architecture:** New `ui/src/components/Onboarding/` tree with one top-level `OnboardingRoot` orchestrating 5 step components. State in a dedicated Zustand store (`onboardingStore`). First-launch detection reads `/settings` on mount; if `onboarding_completed !== true`, render `OnboardingRoot` instead of the normal app shell. On completion, writes the flag via `POST /settings` and falls through to the main app. The flow integrates three existing subsystems — `/settings` (API key storage), the mic + voice pipeline (`/voice/start`, WebSocket `voice.transcript`), and BuilderFlow (`/builder/*`) — no new backend orchestration needed.

**Tech Stack:** React 19 + TypeScript, Zustand (already used), design tokens + motion primitives from Plan 2, existing `api` client with dispatcher routing. No new deps on UI side.

**Prerequisites:**
- Plan 2 Chunks 0-5 complete ✅ (tokens + motion + HUD primitives + showcase). Onboarding ships in the finished visual language from day 1.
- Voice-builder-pilot shipped ✅ (`/builder/start|answer|deploy|cancel` endpoints live in Python).
- Rust Phase 1 complete ✅ — `/config` readable without `.env` editing.
- UI dispatcher in place ✅ — migrated endpoints go to :3006 automatically.

**Unblocks:**
- Tier 1 #4 Settings UI — onboarding writes the same `/settings` values that Settings UI will edit.
- Non-tech friend distribution — after this ships, Premium installer + onboarding = 3-minute install-to-first-agent.

---

## Chunk 1: Onboarding Store + First-Launch Gate

**What:** Stand up the infrastructure — a Zustand store for onboarding state, a first-launch detection hook, and a top-level gate in `App.tsx` that renders `<OnboardingRoot />` (stub for now) when onboarding is incomplete. Nothing user-visible changes yet for existing users because `onboarding_completed` defaults to `true` for installs that predate this plan (we grandfather old sessions).

### Files

- Create: `ui/src/stores/onboardingStore.ts`
- Create: `ui/src/stores/__tests__/onboardingStore.test.ts`
- Create: `ui/src/components/Onboarding/OnboardingRoot.tsx` (stub returning a simple container)
- Create: `ui/src/hooks/useOnboardingGate.ts`
- Create: `ui/src/hooks/__tests__/useOnboardingGate.test.tsx`
- Modify: `ui/src/App.tsx` — render `<OnboardingRoot />` when gate says onboarding is incomplete.

### Tasks

- [ ] **Step 1: Write failing test for onboardingStore**

Create `ui/src/stores/__tests__/onboardingStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useOnboardingStore } from "../onboardingStore";

describe("onboardingStore", () => {
  beforeEach(() => {
    useOnboardingStore.setState({
      currentStep: "welcome",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
    });
  });

  it("starts on welcome step", () => {
    expect(useOnboardingStore.getState().currentStep).toBe("welcome");
  });

  it("advances through steps in order", () => {
    const { advance } = useOnboardingStore.getState();
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("api-key");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("mic-test");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("first-agent");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("landing");
  });

  it("completes on final advance from landing", () => {
    useOnboardingStore.setState({ currentStep: "landing" });
    useOnboardingStore.getState().advance();
    expect(useOnboardingStore.getState().completed).toBe(true);
  });

  it("skip() jumps straight to completed", () => {
    useOnboardingStore.getState().skip();
    expect(useOnboardingStore.getState().completed).toBe(true);
  });
});
```

- [ ] **Step 2: Run test — FAIL (no store yet)**

```bash
cd ui && pnpm test -- src/stores/__tests__/onboardingStore.test.ts
```

- [ ] **Step 3: Implement `ui/src/stores/onboardingStore.ts`**

```typescript
import { create } from "zustand";

export type OnboardingStep =
  | "welcome"
  | "api-key"
  | "mic-test"
  | "first-agent"
  | "landing";

export type ApiProvider = "openai" | "anthropic" | "google" | "deepseek";
export type MicPermission = "unknown" | "granted" | "denied";

const STEP_ORDER: OnboardingStep[] = [
  "welcome",
  "api-key",
  "mic-test",
  "first-agent",
  "landing",
];

interface OnboardingState {
  currentStep: OnboardingStep;
  completed: boolean;
  apiProvider: ApiProvider | null;
  apiKeyValid: boolean;
  micPermission: MicPermission;
  firstAgentSession: string | null;

  advance: () => void;
  back: () => void;
  skip: () => void;
  setApiProvider: (provider: ApiProvider) => void;
  setApiKeyValid: (valid: boolean) => void;
  setMicPermission: (p: MicPermission) => void;
  setFirstAgentSession: (sessionId: string | null) => void;
}

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  currentStep: "welcome",
  completed: false,
  apiProvider: null,
  apiKeyValid: false,
  micPermission: "unknown",
  firstAgentSession: null,

  advance: () => {
    const { currentStep } = get();
    const idx = STEP_ORDER.indexOf(currentStep);
    if (idx === STEP_ORDER.length - 1) {
      set({ completed: true });
    } else {
      set({ currentStep: STEP_ORDER[idx + 1] });
    }
  },
  back: () => {
    const { currentStep } = get();
    const idx = STEP_ORDER.indexOf(currentStep);
    if (idx > 0) set({ currentStep: STEP_ORDER[idx - 1] });
  },
  skip: () => set({ completed: true }),
  setApiProvider: (p) => set({ apiProvider: p }),
  setApiKeyValid: (v) => set({ apiKeyValid: v }),
  setMicPermission: (p) => set({ micPermission: p }),
  setFirstAgentSession: (s) => set({ firstAgentSession: s }),
}));
```

- [ ] **Step 4: Run test — PASS**

```bash
cd ui && pnpm test -- src/stores/__tests__/onboardingStore.test.ts
```
Expected: 4 tests pass.

- [ ] **Step 5: Write failing test for `useOnboardingGate`**

Create `ui/src/hooks/__tests__/useOnboardingGate.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useOnboardingGate } from "../useOnboardingGate";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { settings: vi.fn() },
}));

describe("useOnboardingGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns loading initially, then gated=false when settings say completed", async () => {
    vi.mocked(api.settings).mockResolvedValue({ onboarding_completed: true });
    const { result } = renderHook(() => useOnboardingGate());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(false);
  });

  it("gated=true when onboarding_completed is false or absent", async () => {
    vi.mocked(api.settings).mockResolvedValue({});
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(true);
  });

  it("falls back to gated=true on fetch failure (safer default)", async () => {
    vi.mocked(api.settings).mockRejectedValue(new Error("net"));
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(true);
  });
});
```

- [ ] **Step 6: Run test — FAIL**

```bash
cd ui && pnpm test -- src/hooks/__tests__/useOnboardingGate.test.tsx
```

- [ ] **Step 7: Implement `useOnboardingGate`**

Create `ui/src/hooks/useOnboardingGate.ts`:

```typescript
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useOnboardingStore } from "../stores/onboardingStore";

export interface OnboardingGateResult {
  loading: boolean;
  gated: boolean;
}

export function useOnboardingGate(): OnboardingGateResult {
  const [loading, setLoading] = useState(true);
  const [gated, setGated] = useState(true);
  const storeCompleted = useOnboardingStore((s) => s.completed);

  useEffect(() => {
    let cancelled = false;
    api
      .settings()
      .then((s) => {
        if (cancelled) return;
        const done = s["onboarding_completed"] === true;
        setGated(!done);
        if (done) {
          useOnboardingStore.setState({ completed: true });
        }
      })
      .catch(() => {
        if (!cancelled) setGated(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    loading,
    gated: gated && !storeCompleted,
  };
}
```

- [ ] **Step 8: Run test — PASS**

Expected: 3 tests pass.

- [ ] **Step 9: Create OnboardingRoot stub**

Create `ui/src/components/Onboarding/OnboardingRoot.tsx`:

```tsx
import { useOnboardingStore } from "../../stores/onboardingStore";

export function OnboardingRoot() {
  const step = useOnboardingStore((s) => s.currentStep);
  return (
    <div
      data-onboarding="root"
      data-step={step}
      className="w-full h-full flex items-center justify-center"
      style={{ background: "var(--j-bg)" }}
    >
      {/* Step components mount here in Chunks 2-6 */}
      <div style={{ color: "var(--j-text-dim)" }}>
        onboarding step: {step}
      </div>
    </div>
  );
}
```

- [ ] **Step 10: Wire the gate into `App.tsx`**

In `ui/src/App.tsx`, at the top of the component, read the gate:

```tsx
const { loading: onboardingLoading, gated: onboardingGated } = useOnboardingGate();

if (onboardingLoading) {
  return (
    <div className="w-full h-screen flex items-center justify-center" style={{ background: "var(--j-bg)", color: "var(--j-text-dim)" }}>
      Loading…
    </div>
  );
}
if (onboardingGated) {
  return <OnboardingRoot />;
}
```

Add imports at the top:
```tsx
import { useOnboardingGate } from "./hooks/useOnboardingGate";
import { OnboardingRoot } from "./components/Onboarding/OnboardingRoot";
```

Place the gate check AFTER `useWebSocket()` (so WS connection starts regardless of onboarding state — voice test in Step 3 needs it live).

- [ ] **Step 11: Preview smoke — fresh install shows onboarding**

Start preview. Either:
- Delete any existing `onboarding_completed` in `%APPDATA%/KALI/settings.json` (backend storage location) to force the gate to open, or
- Use eval to mock `api.settings()`: `(await import('/src/stores/onboardingStore.ts')).useOnboardingStore.setState({ completed: false })`

Verify: page renders "onboarding step: welcome" text, no crashes in console.

Use `preview_snapshot` to assert `[data-onboarding='root']` element is present.

- [ ] **Step 12: Run full test suite**

```bash
cd ui && pnpm test && npx tsc --noEmit
```
Expected: all green, no new warnings.

- [ ] **Step 13: Commit**

```bash
git add ui/src/stores/onboardingStore.ts ui/src/stores/__tests__/onboardingStore.test.ts ui/src/components/Onboarding/OnboardingRoot.tsx ui/src/hooks/useOnboardingGate.ts ui/src/hooks/__tests__/useOnboardingGate.test.tsx ui/src/App.tsx
git commit -m "feat(onboarding): infrastructure — store + gate + stub root

Zustand store tracks step progression (welcome -> api-key -> mic-test
-> first-agent -> landing) and per-step data (apiProvider, apiKeyValid,
micPermission, firstAgentSession). useOnboardingGate hook reads the
persisted onboarding_completed flag from /settings on mount; App.tsx
gates the normal UI until the flow completes or explicit skip.

OnboardingRoot is a stub. Step components land in Chunks 2-6."
```

---

## Chunk 2: Step 1 — Welcome Screen

**What:** First-impression screen. Hero text, pulsing HUD orb, a single "Поехали" button. Tone matches JARVIS boot sequence. Uses `<FadeSlideUp>` motion primitive for entry; no API calls, no state mutations beyond `advance()` on button click.

### Files

- Create: `ui/src/components/Onboarding/steps/WelcomeStep.tsx`
- Create: `ui/src/components/Onboarding/steps/__tests__/WelcomeStep.test.tsx`
- Modify: `ui/src/components/Onboarding/OnboardingRoot.tsx` — dispatch step components.

### Tasks

- [ ] **Step 1: Write WelcomeStep test**

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WelcomeStep } from "../WelcomeStep";

describe("WelcomeStep", () => {
  it("renders hero copy and CTA", () => {
    render(<WelcomeStep />);
    expect(screen.getByText(/превратить голос/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /поехали|познакомимся/i })).toBeInTheDocument();
  });

  it("advances onboarding on CTA click", async () => {
    const user = userEvent.setup();
    const advance = vi.fn();
    vi.doMock("../../../../stores/onboardingStore", () => ({
      useOnboardingStore: Object.assign(
        (selector: (s: unknown) => unknown) => selector({ advance }),
        { setState: vi.fn() },
      ),
    }));
    // Re-import after mock
    const { WelcomeStep: Mocked } = await import("../WelcomeStep");
    render(<Mocked />);
    await user.click(screen.getByRole("button", { name: /поехали|познакомимся/i }));
    expect(advance).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Implement `WelcomeStep.tsx`**

```tsx
import { FadeSlideUp } from "../../../motion";
import { PulseOrb } from "../../hud";
import { useOnboardingStore } from "../../../stores/onboardingStore";

export function WelcomeStep() {
  const advance = useOnboardingStore((s) => s.advance);
  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-8 max-w-xl text-center">
        <div className="relative">
          <PulseOrb size={80} status="info" />
        </div>
        <div
          style={{
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-hud)",
            color: "var(--j-text-dim)",
            textTransform: "uppercase",
          }}
        >
          Инициализация · все системы в норме
        </div>
        <h1
          style={{
            fontSize: "var(--j-text-2xl)",
            color: "var(--j-text)",
            lineHeight: "var(--j-leading-tight)",
            maxWidth: "520px",
          }}
        >
          Я — Jarvis. Помогу превратить твой голос в AI-агентов внутри KALI.
        </h1>
        <p style={{ color: "var(--j-text-dim)", maxWidth: "480px" }}>
          Две минуты — и у тебя будет первый работающий агент.
        </p>
        <button
          onClick={advance}
          style={{
            padding: "var(--j-space-3) var(--j-space-6)",
            background: "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
            border: "1px solid var(--j-border-glow)",
            borderRadius: "var(--j-radius-md)",
            color: "var(--j-cyan)",
            fontFamily: "var(--j-font-mono)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
            cursor: "pointer",
            fontSize: "var(--j-text-sm)",
          }}
        >
          Поехали
        </button>
      </div>
    </FadeSlideUp>
  );
}
```

- [ ] **Step 3: Update `OnboardingRoot.tsx` to dispatch**

```tsx
import { useOnboardingStore } from "../../stores/onboardingStore";
import { WelcomeStep } from "./steps/WelcomeStep";

export function OnboardingRoot() {
  const step = useOnboardingStore((s) => s.currentStep);
  return (
    <div
      data-onboarding="root"
      data-step={step}
      className="w-full h-full flex items-center justify-center"
      style={{ background: "var(--j-bg)", minHeight: "100vh", padding: "var(--j-space-8)" }}
    >
      {step === "welcome" && <WelcomeStep />}
      {/* Chunks 3-6 add api-key / mic-test / first-agent / landing */}
    </div>
  );
}
```

- [ ] **Step 4: Run tests + tsc**

```bash
cd ui && pnpm test && npx tsc --noEmit
```

- [ ] **Step 5: Preview smoke**

Start preview, force gate open (see Chunk 1 Step 11), verify Welcome screen renders with hero text + button. Screenshot for proof.

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/Onboarding/
git commit -m "feat(onboarding): step 1 — welcome screen

Hero copy introducing Jarvis (assistant persona) inside KALI (platform).
PulseOrb + mono HUD label + single CTA to advance. Uses FadeSlideUp
motion primitive for entry."
```

---

## Chunk 3: Step 2 — API Key Setup

**What:** Four-provider selector (OpenAI / Anthropic / Google / DeepSeek), API key input, validation via a test LLM call, persistence via `POST /settings`. Skip option routes to a text-only demo mode (apiKeyValid stays false, downstream steps adapt).

### Files

- Create: `ui/src/components/Onboarding/steps/ApiKeyStep.tsx`
- Create: `ui/src/components/Onboarding/steps/__tests__/ApiKeyStep.test.tsx`
- Modify: `ui/src/api/client.ts` — add `testApiKey(provider, key)` method (new `/llm/test` endpoint on Python backend — if not present, add it in Python).
- Modify: `kernel/main.py` — add `POST /llm/test` returning `{ok: bool, error?: str}`.
- Create: `ui/src/components/Onboarding/providers.ts` — provider metadata (label, help URL, placeholder).

### Tasks

- [ ] **Step 1: Add `POST /llm/test` to Python backend**

In `kernel/main.py`, after the existing LLM-related endpoints, add:

```python
@app.post("/llm/test")
async def llm_test(request: Request) -> dict[str, Any]:
    body = await request.json()
    provider = body.get("provider")
    api_key = body.get("api_key")
    if not provider or not api_key:
        return {"ok": False, "error": "provider and api_key are required"}
    try:
        from kernel.llm_router import LLMRequest, LLMRouter
        from kernel.models import LLMConfig
        cfg = LLMConfig(cloud_provider=provider)
        router = LLMRouter(cfg, api_keys={provider: api_key})
        resp = await router.route(LLMRequest(text="ping", available_tools=[]))
        return {"ok": bool(resp.text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

(If `LLMRouter` init signature differs, adapt — goal is one real round-trip to prove the key works.)

Quick verification: start dev backend, `curl -X POST http://127.0.0.1:3005/llm/test -H "Content-Type: application/json" -d '{"provider":"openai","api_key":"sk-bad"}'` → returns `{"ok": false, ...}`.

- [ ] **Step 2: Add client method**

In `ui/src/api/client.ts` (inside the `api` object):

```typescript
testApiKey: (provider: string, apiKey: string) =>
  fetchJSON<{ ok: boolean; error?: string }>("/llm/test", {
    method: "POST",
    body: JSON.stringify({ provider, api_key: apiKey }),
  }),
```

- [ ] **Step 3: Create providers metadata**

`ui/src/components/Onboarding/providers.ts`:

```typescript
import type { ApiProvider } from "../../stores/onboardingStore";

export interface ProviderMeta {
  id: ApiProvider;
  label: string;
  helpUrl: string;
  placeholder: string;
}

export const PROVIDERS: ProviderMeta[] = [
  { id: "openai",    label: "OpenAI",    helpUrl: "https://platform.openai.com/api-keys",    placeholder: "sk-..." },
  { id: "anthropic", label: "Anthropic", helpUrl: "https://console.anthropic.com/settings/keys", placeholder: "sk-ant-..." },
  { id: "google",    label: "Google",    helpUrl: "https://aistudio.google.com/app/apikey",   placeholder: "AIza..." },
  { id: "deepseek",  label: "DeepSeek",  helpUrl: "https://platform.deepseek.com/api_keys",   placeholder: "sk-..." },
];
```

- [ ] **Step 4: Write ApiKeyStep test**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiKeyStep } from "../ApiKeyStep";
import { api } from "../../../../api/client";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

vi.mock("../../../../api/client", () => ({
  api: {
    testApiKey: vi.fn(),
    updateSettings: vi.fn().mockResolvedValue({}),
  },
}));

describe("ApiKeyStep", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOnboardingStore.setState({
      currentStep: "api-key",
      apiProvider: null,
      apiKeyValid: false,
    });
  });

  it("renders 4 provider cards", () => {
    render(<ApiKeyStep />);
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek")).toBeInTheDocument();
  });

  it("validates API key via test endpoint and advances on success", async () => {
    const user = userEvent.setup();
    vi.mocked(api.testApiKey).mockResolvedValue({ ok: true });
    render(<ApiKeyStep />);
    await user.click(screen.getByText("OpenAI"));
    const input = screen.getByPlaceholderText("sk-...");
    await user.type(input, "sk-test-valid");
    await user.click(screen.getByRole("button", { name: /проверить|test/i }));
    await waitFor(() =>
      expect(api.testApiKey).toHaveBeenCalledWith("openai", "sk-test-valid")
    );
    await waitFor(() =>
      expect(useOnboardingStore.getState().apiKeyValid).toBe(true)
    );
  });

  it("shows error on invalid key", async () => {
    const user = userEvent.setup();
    vi.mocked(api.testApiKey).mockResolvedValue({ ok: false, error: "unauthorized" });
    render(<ApiKeyStep />);
    await user.click(screen.getByText("OpenAI"));
    await user.type(screen.getByPlaceholderText("sk-..."), "bad");
    await user.click(screen.getByRole("button", { name: /проверить|test/i }));
    await waitFor(() =>
      expect(screen.getByText(/unauthorized|не подошёл/i)).toBeInTheDocument()
    );
  });

  it("skip path marks apiKeyValid=false and advances", async () => {
    const user = userEvent.setup();
    render(<ApiKeyStep />);
    await user.click(screen.getByRole("button", { name: /пропустить|skip/i }));
    expect(useOnboardingStore.getState().apiKeyValid).toBe(false);
    expect(useOnboardingStore.getState().currentStep).not.toBe("api-key");
  });
});
```

- [ ] **Step 5: Run test — FAIL**

- [ ] **Step 6: Implement `ApiKeyStep.tsx`**

```tsx
import { useState } from "react";
import { PROVIDERS } from "../providers";
import { useOnboardingStore, type ApiProvider } from "../../../stores/onboardingStore";
import { api } from "../../../api/client";
import { HexFrame } from "../../hud";
import { FadeSlideUp } from "../../../motion";

export function ApiKeyStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const setProvider = useOnboardingStore((s) => s.setApiProvider);
  const setValid = useOnboardingStore((s) => s.setApiKeyValid);
  const selected = useOnboardingStore((s) => s.apiProvider);

  const [key, setKey] = useState("");
  const [status, setStatus] = useState<"idle" | "checking" | "valid" | "invalid">("idle");
  const [error, setError] = useState<string | null>(null);

  const meta = PROVIDERS.find((p) => p.id === selected);

  async function handleCheck() {
    if (!selected || !key) return;
    setStatus("checking");
    setError(null);
    try {
      const res = await api.testApiKey(selected, key);
      if (res.ok) {
        setStatus("valid");
        setValid(true);
        await api.updateSettings({ [`api_key_${selected}`]: key });
        setTimeout(() => advance(), 600);
      } else {
        setStatus("invalid");
        setError(res.error ?? "Ключ не подошёл. Проверь ещё раз.");
      }
    } catch (e) {
      setStatus("invalid");
      setError(e instanceof Error ? e.message : "unknown error");
    }
  }

  function handleSkip() {
    setValid(false);
    advance();
  }

  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-6 max-w-2xl w-full">
        <h2 style={{ fontSize: "var(--j-text-xl)", color: "var(--j-text)", textAlign: "center" }}>
          Чтобы я думал, дай ключ от мозга
        </h2>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "var(--j-space-3)", width: "100%" }}>
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              onClick={() => {
                setProvider(p.id);
                setStatus("idle");
                setError(null);
              }}
              style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
            >
              <HexFrame active={selected === p.id}>
                <div style={{ padding: "var(--j-space-4)", textAlign: "center", color: "var(--j-text)" }}>
                  {p.label}
                </div>
              </HexFrame>
            </button>
          ))}
        </div>

        {meta && (
          <div className="flex flex-col items-center gap-3 w-full">
            <a
              href={meta.helpUrl}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: "var(--j-text-xs)", color: "var(--j-cyan-dim)", letterSpacing: "var(--j-tracking-wide)" }}
            >
              Где взять ключ {meta.label} →
            </a>
            <input
              type="password"
              placeholder={meta.placeholder}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              style={{
                width: "100%", maxWidth: "420px",
                padding: "var(--j-space-3) var(--j-space-4)",
                background: "var(--j-surface)",
                border: `1px solid ${status === "invalid" ? "var(--j-danger)" : "var(--j-border)"}`,
                borderRadius: "var(--j-radius-md)",
                color: "var(--j-text)",
                fontFamily: "var(--j-font-mono)",
              }}
            />
            <button
              onClick={handleCheck}
              disabled={!key || status === "checking"}
              style={{
                padding: "var(--j-space-3) var(--j-space-6)",
                background: status === "valid"
                  ? "color-mix(in srgb, var(--j-success) 20%, transparent)"
                  : "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
                border: `1px solid ${status === "valid" ? "var(--j-success)" : "var(--j-border-glow)"}`,
                borderRadius: "var(--j-radius-md)",
                color: status === "valid" ? "var(--j-success)" : "var(--j-cyan)",
                fontFamily: "var(--j-font-mono)", letterSpacing: "var(--j-tracking-wide)",
                textTransform: "uppercase", cursor: "pointer", fontSize: "var(--j-text-sm)",
              }}
            >
              {status === "checking" ? "Проверяю..." : status === "valid" ? "✓ Ключ работает" : "Проверить"}
            </button>
            {error && <div style={{ color: "var(--j-danger)", fontSize: "var(--j-text-sm)" }}>{error}</div>}
          </div>
        )}

        <button
          onClick={handleSkip}
          style={{ background: "transparent", border: "none", color: "var(--j-text-muted)", cursor: "pointer", fontSize: "var(--j-text-xs)", letterSpacing: "var(--j-tracking-wide)", textTransform: "uppercase" }}
        >
          У меня нет ключа — пропустить
        </button>
      </div>
    </FadeSlideUp>
  );
}
```

- [ ] **Step 7: Wire into OnboardingRoot**

Add to the dispatch block:
```tsx
{step === "api-key" && <ApiKeyStep />}
```

- [ ] **Step 8: Run tests + tsc**

- [ ] **Step 9: Preview smoke**

Verify: selecting a provider reveals the input, fake-good key triggers "Ключ работает" + advance, bad key shows error, skip works.

- [ ] **Step 10: Commit**

```bash
git add ui/src/components/Onboarding/ ui/src/api/client.ts kernel/main.py
git commit -m "feat(onboarding): step 2 — api key setup with live validation

Four-provider selector, HexFrame tiles, inline validation via new
POST /llm/test endpoint (Python). On success, persists api_key_<provider>
via POST /settings and advances. Skip path proceeds with apiKeyValid=false
— downstream steps adapt to text-only mode."
```

---

## Chunk 4: Step 3 — Mic Permission + Voice Test

**What:** Trigger browser mic permission, transcribe a test utterance ("Jarvis, привет"), play back a TTS confirmation. Uses existing `/voice/start` + WebSocket `voice.transcript` event. If mic denied, show clear error + skip option to text-only mode.

### Files

- Create: `ui/src/components/Onboarding/steps/MicTestStep.tsx`
- Create: `ui/src/components/Onboarding/steps/__tests__/MicTestStep.test.tsx`

### Tasks

- [ ] **Step 1: Write MicTestStep test**

Mock `navigator.mediaDevices.getUserMedia` + the api client. Assert:
- On mount, requests permission.
- On granted, subscribes to `voice.transcript` events.
- When a transcript event arrives, shows the text.
- On denied, shows error + skip option.
- Skip advances with `micPermission="denied"`.

(Full test code follows the pattern established in Chunk 3 Step 4.)

- [ ] **Step 2: Implement `MicTestStep.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { useVoiceStore } from "../../../stores/voiceStore";
import { api } from "../../../api/client";
import { FadeSlideUp } from "../../../motion";
import { PulseOrb } from "../../hud";

export function MicTestStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const setMic = useOnboardingStore((s) => s.setMicPermission);
  const transcript = useVoiceStore((s) => s.transcript);
  const [state, setState] = useState<"requesting" | "listening" | "heard" | "denied">("requesting");
  const advanceRef = useRef(advance);
  advanceRef.current = advance;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
        if (cancelled) return;
        setMic("granted");
        await api.voiceStart();
        setState("listening");
      } catch {
        if (!cancelled) {
          setMic("denied");
          setState("denied");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setMic]);

  useEffect(() => {
    if (state === "listening" && transcript && transcript.length > 0) {
      setState("heard");
      setTimeout(() => advanceRef.current(), 1500);
    }
  }, [state, transcript]);

  const headline =
    state === "requesting" ? "Разрешаю доступ к микрофону..." :
    state === "listening" ? "Скажи: «Джарвис, привет»" :
    state === "heard" ? "Слышу тебя отлично." :
    "Микрофон не разрешён.";

  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-6 max-w-xl text-center">
        <PulseOrb size={64} active={state !== "denied"} status={state === "heard" ? "success" : "info"} />
        <h2 style={{ fontSize: "var(--j-text-xl)", color: "var(--j-text)" }}>{headline}</h2>
        {transcript && state === "listening" && (
          <div style={{ color: "var(--j-cyan)", fontFamily: "var(--j-font-mono)", fontSize: "var(--j-text-sm)" }}>
            {transcript}
          </div>
        )}
        {state === "denied" && (
          <button
            onClick={() => advance()}
            style={{
              padding: "var(--j-space-3) var(--j-space-6)",
              background: "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
              border: "1px solid var(--j-border-glow)",
              borderRadius: "var(--j-radius-md)",
              color: "var(--j-cyan)",
              fontFamily: "var(--j-font-mono)",
              letterSpacing: "var(--j-tracking-wide)",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            Пропустить — только текст
          </button>
        )}
      </div>
    </FadeSlideUp>
  );
}
```

- [ ] **Step 3: Wire into OnboardingRoot**

```tsx
{step === "mic-test" && <MicTestStep />}
```

- [ ] **Step 4: Run tests + tsc + preview**

Manual preview requires real mic — at minimum verify the "denied" path renders (in automation, mock navigator).

- [ ] **Step 5: Commit**

```
feat(onboarding): step 3 — mic permission + voice test
```

---

## Chunk 5: Step 4 — First Agent Creation

**What:** The magic moment. Suggested example chips (5 starter agents) + voice/text input. On submission, calls `POST /builder/start` to begin BuilderFlow (from voice-builder-pilot), then renders BuilderFlow's own dialog UI for answers. When deployed, advance.

### Files

- Create: `ui/src/components/Onboarding/steps/FirstAgentStep.tsx`
- Create: `ui/src/components/Onboarding/steps/__tests__/FirstAgentStep.test.tsx`

Uses existing `api.builderClassify` / `api.builderCreateSkill` (from voice-builder-pilot).

### Tasks

High-level (detailed steps follow established patterns from Chunks 2-4):

- [ ] Define 5 starter examples: "напомни пить воду каждые 2 часа", "дневник настроения вечером", "трекер трат по скринам чеков", "погода утром в 8:00", "список продуктов по фото холодильника".
- [ ] Implement chip grid + text input (or voice input if `apiKeyValid` and `micPermission === "granted"`).
- [ ] On submit, open BuilderPanel sub-flow inline (import from `ui/src/components/Builder/`).
- [ ] When BuilderFlow emits `deploy` success event, set `firstAgentSession` in store and call `advance()`.
- [ ] Tests cover: chips render, submitting via chip triggers builder call, deploy success advances flow.
- [ ] Commit: `feat(onboarding): step 4 — first agent creation via BuilderFlow`

---

## Chunk 6: Step 5 — Landing

**What:** Quick transition — fade out onboarding, fade in main app with 1 agent visible in the list. Calls `api.updateSettings({ onboarding_completed: true })` and clears the gate.

### Files

- Create: `ui/src/components/Onboarding/steps/LandingStep.tsx`
- Create: `ui/src/components/Onboarding/steps/__tests__/LandingStep.test.tsx`

### Tasks

- [ ] Minimal component: shows "Добро пожаловать домой" + brief tooltip indicating mic button. After 2-3 seconds, automatically completes.
- [ ] On mount, writes `onboarding_completed: true` to `/settings`.
- [ ] Uses `useOnboardingGate` indirectly — once `completed` is true, `App.tsx` re-renders main shell.
- [ ] Test: verifies `api.updateSettings` is called with `{ onboarding_completed: true }` on mount.
- [ ] Commit: `feat(onboarding): step 5 — landing + gate closure`

---

## Chunk 7: Integration Polish + Restart Entry Point

**What:** Tie up loose ends — Settings UI gets a "Пройти onboarding заново" button (covered in the Settings UI plan, but we wire the action here), keyboard navigation (Esc to skip), a11y pass, animated transitions between steps.

### Files

- Modify: `ui/src/components/Onboarding/OnboardingRoot.tsx` — add transition wrapper, keyboard listener.
- Create: `ui/src/components/Onboarding/__tests__/integration.test.tsx` — end-to-end flow test.

### Tasks

- [ ] Wrap step switch in `AnimatePresence` (from framer-motion) for cross-fade.
- [ ] Global Esc listener to trigger `skip()`.
- [ ] Integration test: renders `<OnboardingRoot />`, programmatically advances through all 5 steps, asserts final state has `completed: true`.
- [ ] Manual full-flow preview smoke: fresh install → welcome → api-key (fake provider) → mic skip → agent skip (or real if time) → landing → main app. Screenshot each step.
- [ ] Commit: `feat(onboarding): integration polish — transitions, keyboard shortcuts, e2e test`

---

## Success Criteria (whole plan)

- ✅ Fresh install automatically shows onboarding; completed installs skip it.
- ✅ Each step renders with design tokens + motion primitives — no hardcoded colours.
- ✅ API key validation actually calls the LLM once and reports real errors.
- ✅ Mic test uses real `getUserMedia` + existing voice pipeline; graceful degrade on denial.
- ✅ First-agent step successfully creates and deploys via BuilderFlow.
- ✅ `onboarding_completed` flag persists across app restarts.
- ✅ All chunks have unit tests, full `pnpm test` + `npx tsc --noEmit` green at every commit.
- ✅ Screen recording of full flow under 2 minutes (pick a real case, 5 non-tech testers reach first agent).

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Mic permission prompt is OS-level and can feel invasive | Explicit explanation text before the prompt; user can retry or skip. |
| API key validation call counts toward user's quota | First call is one round-trip of ~100 tokens — acceptable. Document in step copy. |
| BuilderFlow integration mid-onboarding adds state complexity | BuilderFlow already works standalone; we just invoke it inside our step. State stays in its own store. |
| "Пропустить" rate too high | If > 20% skip, re-cut copy. A/B test post-v1 only — no preemptive optimisation. |
| First-agent deploy fails mid-demo | Show retry + "Cancel for now" option; do not block landing. `firstAgentSession: null` is a valid final state. |
| Onboarding blocks tech users who don't want it | Settings → "Replay onboarding" lets them opt in later; first-run still runs it once. Escape key triggers skip. |
| `/settings` contract drift once Rust migrates `/settings` (later) | Current `/settings` stays Python through Phase 1; onboarding uses Python. Rust migration of `/settings` (Phase 4 or later) will match the JSON shape — onboarding unaffected. |

## Estimate

3-4 days solo. Chunks 1-3 can land day 1. Chunks 4-5 are the trickiest (real mic + real BuilderFlow integration) — day 2-3. Chunk 6-7 polish — day 4.
