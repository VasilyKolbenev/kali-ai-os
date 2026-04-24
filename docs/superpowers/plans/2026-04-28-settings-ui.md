# Settings UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing `ui/src/components/Settings/Settings.tsx` (307 lines, functional but not design-token-aware and missing live key validation / voice controls / onboarding replay) into a complete non-tech Settings surface. After this ships, no user needs to touch `%APPDATA%/KALI/.env` for day-to-day configuration.

**Architecture:** Keep the single-page Settings surface (one mode in `AppMode`). Decompose the monolithic `Settings.tsx` into three section components (`LlmSettings`, `VoiceSettings`, `AdvancedSettings`) plus a shared `SecretField` primitive. State stays local for now (no Zustand store — settings are short-lived view state). All persistence goes through `api.settings()` / `api.updateSettings()` (already dispatcher-aware). Live key validation reuses `api.testApiKey()` from onboarding. A "Replay onboarding" button resets `onboarding_completed` and the gate picks it up.

**Tech Stack:** Existing — React 19, design tokens + HUD primitives + motion primitives from Plan 2. No new deps.

**Prerequisites:**
- Plan 2 Chunks 0-5 complete ✅ (tokens, HexFrame, HudDivider, FadeSlideUp).
- Onboarding Chunks 1-7 complete ✅ (SecretField pattern established in ApiKeyStep, `api.testApiKey` wired).
- Rust Phase 1 complete ✅ (`/config` read native; `/settings` still Python — POST route unchanged).

**Unblocks:**
- Tier 1 #6 Feedback channel — has ergonomic place to expose the "Отправить лог разработчику" button.
- Voice tuning from the product surface (change F5 reference, wake word, idle thresholds) without config.yaml editing.
- Friend-testing — third-party testers can fix misconfig (wrong key pasted, wrong provider selected) without dev intervention.

---

## Chunk 1: Shared SecretField + refactor current Settings to use api client

**What:** Extract the password-masked + test-key-button pattern (currently inlined in onboarding's `ApiKeyStep`) into a reusable `<SecretField>` component. Replace the raw `fetch(apiUrl(...))` calls in `Settings.tsx` with `api.settings()` / `api.updateSettings()` from `client.ts` (which already goes through the dispatcher). Nothing user-visible changes yet — purely plumbing.

### Files

- Create: `ui/src/components/Settings/SecretField.tsx`
- Create: `ui/src/components/Settings/__tests__/SecretField.test.tsx`
- Modify: `ui/src/components/Settings/Settings.tsx` — switch from raw fetch to `api` client; break the single component into top-level plus `LlmSettings` stub file (further decomposition in Chunk 2).
- Create: `ui/src/components/Settings/sections/LlmSettings.tsx` (minimal: wraps current LLM UI)

### Tasks

- [ ] **Step 1: Write SecretField test**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecretField } from "../SecretField";

describe("SecretField", () => {
  it("masks value by default and toggles on show", async () => {
    const user = userEvent.setup();
    render(<SecretField value="abc123" onChange={() => {}} placeholder="sk-..." />);
    const input = screen.getByPlaceholderText("sk-...") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.click(screen.getByRole("button", { name: /показать|show/i }));
    expect(input.type).toBe("text");
  });

  it("calls onTest when test button clicked", async () => {
    const user = userEvent.setup();
    const onTest = vi.fn();
    render(<SecretField value="k" onChange={() => {}} placeholder="x" onTest={onTest} />);
    await user.click(screen.getByRole("button", { name: /проверить|test/i }));
    expect(onTest).toHaveBeenCalledOnce();
  });

  it("renders status indicator when provided", () => {
    render(<SecretField value="k" onChange={() => {}} placeholder="x" status="valid" />);
    expect(screen.getByText(/активен|valid/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement `SecretField.tsx`**

```tsx
import { useState } from "react";

type Status = "unknown" | "checking" | "valid" | "invalid";

interface SecretFieldProps {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  onTest?: () => void;
  status?: Status;
}

export function SecretField({ value, onChange, placeholder, onTest, status = "unknown" }: SecretFieldProps) {
  const [visible, setVisible] = useState(false);
  const statusLabel =
    status === "valid" ? "● активен" :
    status === "invalid" ? "● ошибка" :
    status === "checking" ? "● проверяю..." :
    "○ не настроен";
  const statusColor =
    status === "valid" ? "var(--j-success)" :
    status === "invalid" ? "var(--j-danger)" :
    status === "checking" ? "var(--j-amber)" :
    "var(--j-text-muted)";

  return (
    <div className="flex items-center gap-2 w-full">
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          flex: 1,
          padding: "var(--j-space-2) var(--j-space-3)",
          background: "var(--j-surface)",
          border: "1px solid var(--j-border)",
          borderRadius: "var(--j-radius-md)",
          color: "var(--j-text)",
          fontFamily: "var(--j-font-mono)",
          fontSize: "var(--j-text-sm)",
        }}
      />
      <button
        onClick={() => setVisible(!visible)}
        title={visible ? "Скрыть" : "Показать"}
        style={{ background: "transparent", border: "none", color: "var(--j-text-dim)", cursor: "pointer" }}
      >
        {visible ? "🙈" : "👁"}
      </button>
      {onTest && (
        <button
          onClick={onTest}
          disabled={!value || status === "checking"}
          style={{
            padding: "var(--j-space-2) var(--j-space-3)",
            background: "color-mix(in srgb, var(--j-cyan) 12%, transparent)",
            border: "1px solid var(--j-border-glow)",
            borderRadius: "var(--j-radius-md)",
            color: "var(--j-cyan)",
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
            cursor: "pointer",
          }}
        >
          Проверить
        </button>
      )}
      <span style={{ fontSize: "var(--j-text-xs)", color: statusColor, fontFamily: "var(--j-font-mono)", minWidth: "90px" }}>
        {statusLabel}
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Refactor Settings.tsx to use api client**

Replace all raw `fetch(apiUrl(...))` calls with `api.settings()` / `api.updateSettings()`. The dispatch layer handles routing. Keep the existing shape of SettingsData — no backend changes in this chunk.

Extract the LLM block into `ui/src/components/Settings/sections/LlmSettings.tsx`. The parent Settings becomes a thin shell that loads data and renders sections.

- [ ] **Step 4: Run tests + tsc + preview**

- [ ] **Step 5: Commit**

```
feat(settings): SecretField primitive + refactor to api client (Chunk 1)
```

---

## Chunk 2: Apply design tokens + HexFrame/HudDivider polish

**What:** Replace Tailwind/hex literals in Settings with design tokens and HUD primitives. Section titles use `<HudDivider label="...">`, provider cards use `<HexFrame active={...}>`, typography follows the mono/uppercase HUD convention. Visual parity with Onboarding.

### Files

- Modify: `ui/src/components/Settings/Settings.tsx` (shell styling)
- Modify: `ui/src/components/Settings/sections/LlmSettings.tsx` (section styling)

### Tasks

- [ ] Wrap each section with `<HudDivider label="LLM ПРОВАЙДЕРЫ">` etc.
- [ ] Replace provider tabs with `<HexFrame active={selected === p.id}>` cards
- [ ] Replace all `bg-[var(...)]` / hex literals with token references + `color-mix()` where alpha is needed
- [ ] Save button styling matches onboarding CTA pattern
- [ ] Preview smoke across all sections, screenshot before/after
- [ ] Commit: `feat(settings): design-token polish (Chunk 2)`

---

## Chunk 3: Voice Settings Section (wake word + auto_start + mode)

**What:** New section exposes wake-word, auto_start, mic mode, stt_model from `config/kali.yaml`. Changes persist via PUT `/config` (to be added — Python writes back to yaml). Until then, changes fall back to `/settings` key-value storage which `config_manager` reads at startup.

### Files

- Create: `ui/src/components/Settings/sections/VoiceSettings.tsx`
- Create: `ui/src/components/Settings/sections/__tests__/VoiceSettings.test.tsx`
- Modify: `kernel/main.py` — add `PUT /config` that writes select fields to YAML on disk (voice.*, llm.*). For Phase 1 simplicity, accept full new config body, validate via Pydantic, write.

### Tasks

- [ ] Python: `PUT /config` handler writes file and triggers `config_manager.reload()` via `ConfigManager.reload()` (add method if absent — re-parse yaml, emit event bus "config.changed").
- [ ] UI: VoiceSettings renders 3 fields (wake_word text, auto_start toggle, mode radio: wake_word|continuous|off).
- [ ] Saves on "Применить" button (no auto-save — avoid partial state).
- [ ] 3 tests: renders current values, toggle flips, save triggers api.updateConfig.
- [ ] Commit: `feat(settings): voice section — wake word, auto-start, mode (Chunk 3)`

---

## Chunk 4: Live Key Validation in Settings

**What:** Wire `api.testApiKey()` (from onboarding Chunk 3) into each provider's SecretField in LlmSettings. Shows live status indicator (unknown/checking/valid/invalid). Invalid keys block save.

### Files

- Modify: `ui/src/components/Settings/sections/LlmSettings.tsx`
- Modify: `ui/src/components/Settings/__tests__/LlmSettings.test.tsx`

### Tasks

- [ ] Each provider has its own status state. User types key → status=unknown. Click "Проверить" → status=checking → api.testApiKey → valid/invalid.
- [ ] Save button disabled when any field has status=invalid (warn before saving).
- [ ] Test: check button triggers testApiKey, valid result updates status, save works only when all OK.
- [ ] Commit: `feat(settings): live LLM key validation in LlmSettings (Chunk 4)`

---

## Chunk 5: Replay Onboarding + Advanced Section

**What:** "Прогнать onboarding заново" button wipes `onboarding_completed=false`; the existing gate picks it up on mount and shows OnboardingRoot on next load (or immediately if we dispatch store change). Also adds Advanced section: log level, models dir path display, version, update-check stub.

### Files

- Create: `ui/src/components/Settings/sections/AdvancedSettings.tsx`
- Modify: `ui/src/components/Settings/Settings.tsx` — mount the new section.
- Modify: `ui/src/stores/onboardingStore.ts` — add `reset()` action.

### Tasks

- [ ] onboardingStore.reset() clears completed, resets to welcome, also writes `api.updateSettings({ onboarding_completed: false })`.
- [ ] AdvancedSettings renders version (via `api.version()`), models dir (read-only from /voice/status), log level select (info/debug), "Прогнать onboarding заново" button.
- [ ] Button calls onboardingStore.reset() and alerts "Onboarding will start on next launch."
- [ ] Actually better: reload the page after reset so gate fires immediately.
- [ ] Test: reset action writes to settings + flips store.
- [ ] Commit: `feat(settings): advanced section + replay onboarding (Chunk 5)`

---

## Success Criteria (whole plan)

- ✅ All sections styled with design tokens; no raw hex/rgba in Settings/*.
- ✅ Every LLM provider key has live validation via "Проверить" button.
- ✅ Wake word / auto_start / mode editable from UI and persisted.
- ✅ Replay-onboarding button works (one click → onboarding shows on next launch / after reload).
- ✅ Non-tech user can configure OpenAI + change wake word in ≤5 minutes without opening any file.
- ✅ `npx tsc --noEmit` + `pnpm test` green at each commit.

## Out of Scope (deferred to later plans)

- OAuth flows (Google Calendar / Gmail / Home Assistant / Telegram). Each is its own plan — 1-3 days depending on provider. Deferred until after Feedback channel (Tier 1 #6).
- Secure key storage via `keytar` / OS keychain — deferred until after first friend-distribution. MVP is `.env` file (already the case).
- Import/export config — deferred; low immediate value.
- Per-agent config editor — lives in Agent Store v2 plan.
- Cloud sync settings — post-mobile.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Writing `config/kali.yaml` corrupts user's edits | Backup to `kali.yaml.bak` before each write. Document in PUT handler. |
| Hot-reload vs voice pipeline state drift | Voice config changes require explicit "Apply + restart" button, not auto. |
| Test-key call costs money | Each /llm/test costs ~$0.001. Fine for on-demand. Not automatic. |
| Replay-onboarding wipes user's API key | Reset only touches `onboarding_completed`, not api_key_*. Verify in Chunk 5 test. |
| Config YAML schema drift over time | Pydantic validation on PUT rejects invalid shape; UI matches schema. |

## Estimate

2-3 days solo. Chunk 1 (infrastructure) day 1 morning. Chunks 2-3 day 1 afternoon + day 2. Chunks 4-5 day 2 afternoon + day 3.
