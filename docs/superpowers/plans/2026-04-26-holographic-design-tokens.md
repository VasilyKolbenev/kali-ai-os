# Holographic Design Tokens Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the foundation layer (design tokens + motion helpers + HUD component primitives) that every subsequent surface redesign (onboarding, settings, agent store v2, цифровой статус) consumes. Unify existing hardcoded colours/animations behind a single source of truth so the next four plans can move fast without visual drift.

**Architecture:** Extend the existing `ui/src/index.css` token layer (`--j-*` CSS custom properties — already 135 usages across 21 files) into split files under `ui/src/tokens/` with a TypeScript mirror for autocomplete. Build a thin Framer Motion wrapper layer (`ui/src/motion/`) that respects `prefers-reduced-motion`. Add four HUD primitives (`<HexFrame>`, `<PulseOrb>`, `<HudDivider>`, `<ScanLineBg>`) under `ui/src/components/hud/`. Expose everything through a new `/showcase` dev route. Finally, migrate three existing surfaces (`ArcReactor`, `Sidebar`, `ChatInput`) off hardcoded colours and onto tokens to prove the system holds without visual regressions.

**Tech Stack:** CSS custom properties, TypeScript, React 19, Framer Motion 11, Tailwind 4 (already in project), Vitest + @testing-library/react for tests.

**Design stance — Level 1 + cherry-pick Level 2. Level 3 (full 3D) deferred until 100+ active users.** Anti-Marvel vocab: "Ядро KALI" / "Интерфейс" / "Контур" (not "Arc Reactor" / "HUD" / "Mark XLII"). Voice-related visuals refer to **Jarvis** (the assistant persona), everything platform-level refers to **KALI**.

**Prerequisites:** None — this is the foundation. Nothing blocks it.

**Unblocks:** `2026-04-27-onboarding-flow`, `2026-04-28-settings-ui`, `2026-04-30-agent-store-v2`, `2026-05-01-tsifrovoy-status`.

---

## Chunk 0: Test Infrastructure

**What:** Install and configure Vitest + React Testing Library + jsdom. The UI project ships zero tests today and no test framework in `devDependencies` — Chunks 1-4 can't run their `npx vitest run` steps without this. One-time setup, then every subsequent chunk's test step works.

### Files

- Modify: `ui/package.json` — add devDeps + `test` / `test:watch` scripts
- Create: `ui/vitest.config.ts`
- Create: `ui/src/test/setup.ts`
- Create: `ui/src/__tests__/smoke.test.ts`
- Modify: `ui/tsconfig.json` — include vitest globals type

### Tasks

- [ ] **Step 1: Install dev dependencies**

Run from project root:
```bash
cd ui && npm install -D vitest @vitest/ui @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

Expected: packages installed, `ui/package.json` updated. `ui/package-lock.json` or `ui/pnpm-lock.yaml` regenerated — whichever exists.

- [ ] **Step 2: Create `ui/vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
```

- [ ] **Step 3: Create `ui/src/test/setup.ts`**

```typescript
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount React trees between tests so DOM state doesn't leak.
afterEach(() => {
  cleanup();
});
```

- [ ] **Step 4: Add test scripts to `ui/package.json`**

In the `"scripts"` object, after `"preview"`, add:
```json
"test": "vitest run",
"test:watch": "vitest",
"test:ui": "vitest --ui"
```

- [ ] **Step 5: Update `ui/tsconfig.json` to include vitest types**

In `compilerOptions.types` (create the array if absent), add `"vitest/globals"` and `"@testing-library/jest-dom"`. Example:
```json
{
  "compilerOptions": {
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  }
}
```

Keep all other `tsconfig.json` settings untouched.

- [ ] **Step 6: Create `ui/src/__tests__/smoke.test.ts`**

```typescript
import { describe, it, expect } from "vitest";

describe("test infrastructure", () => {
  it("runs vitest + jsdom", () => {
    const div = document.createElement("div");
    div.textContent = "hello";
    expect(div.textContent).toBe("hello");
  });

  it("exposes matchers from jest-dom", () => {
    document.body.innerHTML = '<button disabled>x</button>';
    const btn = document.querySelector("button")!;
    expect(btn).toBeDisabled();
  });
});
```

- [ ] **Step 7: Run the smoke test**

Run: `cd ui && npm test -- src/__tests__/smoke.test.ts`
Expected: 2 tests PASS.

- [ ] **Step 8: Run tsc to confirm no type regressions**

Run: `cd ui && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/pnpm-lock.yaml ui/vitest.config.ts ui/src/test/ ui/src/__tests__/ ui/tsconfig.json
git commit -m "chore(ui): add vitest + testing-library + jsdom infrastructure

Prerequisite for all UI unit tests. Smoke test verifies jsdom + jest-dom
matchers work end-to-end. npm test / test:watch / test:ui scripts added."
```

(Only stage the lock file that actually exists — ignore the other.)

---

## Chunk 1: Token System Expansion

**What:** Extract the existing `--j-*` CSS vars from `ui/src/index.css` into a focused `ui/src/tokens/` directory with one file per concern (colours, typography, spacing, elevation, motion). Add missing tokens. Provide a TypeScript re-export for compile-time autocomplete. Ensure zero visual regressions — existing consumers continue to work via the same `var(--j-*)` names.

### Files

- Create: `ui/src/tokens/colors.css`
- Create: `ui/src/tokens/typography.css`
- Create: `ui/src/tokens/spacing.css`
- Create: `ui/src/tokens/elevation.css`
- Create: `ui/src/tokens/motion.css`
- Create: `ui/src/tokens/index.css` (barrel)
- Create: `ui/src/tokens/index.ts` (TS mirror for static consumers)
- Modify: `ui/src/index.css` — replace inline `--j-*` block with `@import "./tokens/index.css";`
- Modify: `ui/src/main.tsx` — verify `import "./index.css"` still present (no change expected; just verify)
- Test: `ui/src/tokens/__tests__/tokens.test.ts`

### Tasks

- [ ] **Step 1: Scaffold `ui/src/tokens/colors.css` with the current palette plus additions**

Copy the existing `--j-bg`, `--j-surface*`, `--j-border*`, `--j-cyan*`, `--j-amber`, `--j-green`, `--j-red`, `--j-text*` vars verbatim from `ui/src/index.css` lines 4-20. Then add the following tiers (missing today):

```css
:root {
  /* Existing — copy from index.css */
  --j-bg: #050508;
  --j-surface: rgba(255, 255, 255, 0.03);
  --j-surface-hover: rgba(255, 255, 255, 0.06);
  --j-border: rgba(255, 255, 255, 0.06);
  --j-border-glow: rgba(0, 212, 255, 0.15);
  --j-cyan: #00d4ff;
  --j-cyan-dim: rgba(0, 212, 255, 0.6);
  --j-cyan-glow: rgba(0, 212, 255, 0.12);
  --j-amber: #ffb800;
  --j-green: #00e676;
  --j-red: #ff3d57;
  --j-text: #e8eaed;
  --j-text-dim: rgba(255, 255, 255, 0.4);
  --j-text-muted: rgba(255, 255, 255, 0.2);

  /* NEW — semantic cyan tiers */
  --j-cyan-strong: rgba(0, 212, 255, 0.85);
  --j-cyan-soft: rgba(0, 212, 255, 0.35);
  --j-cyan-wash: rgba(0, 212, 255, 0.05);

  /* NEW — status tiers (used by state indicators, toasts) */
  --j-success: var(--j-green);
  --j-success-glow: rgba(0, 230, 118, 0.25);
  --j-warning: var(--j-amber);
  --j-warning-glow: rgba(255, 184, 0, 0.25);
  --j-danger: var(--j-red);
  --j-danger-glow: rgba(255, 61, 87, 0.25);

  /* NEW — offline/disabled visual state (matches ArcReactor.tsx 'offline' config) */
  --j-offline: #4a5568;
  --j-offline-glow: rgba(74, 85, 104, 0.2);
}
```

- [ ] **Step 2: Scaffold `ui/src/tokens/typography.css`**

```css
:root {
  --j-font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
  --j-font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;

  /* NEW — modular scale (1.25 ratio from 14px body) */
  --j-text-xs: 0.72rem;   /* 11.5px — metadata, timestamps */
  --j-text-sm: 0.875rem;  /* 14px — body default */
  --j-text-base: 1rem;    /* 16px — UI labels */
  --j-text-lg: 1.25rem;   /* 20px — section headers */
  --j-text-xl: 1.563rem;  /* 25px — page titles */
  --j-text-2xl: 1.953rem; /* 31px — hero */

  --j-leading-tight: 1.2;
  --j-leading-normal: 1.5;
  --j-leading-relaxed: 1.75;

  --j-tracking-tight: -0.01em;
  --j-tracking-normal: 0;
  --j-tracking-wide: 0.05em;   /* mono labels, HUD metadata */
  --j-tracking-hud: 0.15em;    /* ALL-CAPS HUD text */
}
```

- [ ] **Step 3: Scaffold `ui/src/tokens/spacing.css`**

```css
:root {
  /* 4px base grid */
  --j-space-0: 0;
  --j-space-1: 0.25rem;  /* 4px */
  --j-space-2: 0.5rem;   /* 8px */
  --j-space-3: 0.75rem;  /* 12px */
  --j-space-4: 1rem;     /* 16px */
  --j-space-5: 1.5rem;   /* 24px */
  --j-space-6: 2rem;     /* 32px */
  --j-space-8: 3rem;     /* 48px */
  --j-space-12: 5rem;    /* 80px */

  --j-radius-sm: 4px;
  --j-radius-md: 8px;
  --j-radius-lg: 16px;
  --j-radius-xl: 24px;
  --j-radius-full: 9999px;

  /* Hex-clip corner offset for HexFrame (Level 2 motif) */
  --j-hex-corner: 14px;
}
```

- [ ] **Step 4: Scaffold `ui/src/tokens/elevation.css` (glow-shadows, not drop-shadows)**

```css
:root {
  /* Levels 0-3: no blur, soft glow, medium glow, strong glow */
  --j-elev-0: none;
  --j-elev-1: 0 0 12px var(--j-cyan-glow);
  --j-elev-2: 0 0 24px var(--j-cyan-glow), 0 0 48px rgba(0, 212, 255, 0.06);
  --j-elev-3: 0 0 32px var(--j-cyan-soft), 0 0 80px var(--j-cyan-glow);

  /* Inset glow for hover/focus */
  --j-elev-inset: inset 0 0 20px var(--j-cyan-wash);
}
```

- [ ] **Step 5: Scaffold `ui/src/tokens/motion.css`**

```css
:root {
  --j-duration-fast: 150ms;
  --j-duration-base: 300ms;
  --j-duration-slow: 600ms;

  /* Standard easings */
  --j-ease-out: cubic-bezier(0.2, 0.8, 0.2, 1);         /* confident exit */
  --j-ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);        /* default */
  --j-ease-expo: cubic-bezier(0.16, 1, 0.3, 1);         /* dramatic reveal */
}

@media (prefers-reduced-motion: reduce) {
  :root {
    --j-duration-fast: 0ms;
    --j-duration-base: 0ms;
    --j-duration-slow: 0ms;
  }
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 6: Create `ui/src/tokens/index.css` barrel**

```css
@import "./colors.css";
@import "./typography.css";
@import "./spacing.css";
@import "./elevation.css";
@import "./motion.css";
```

- [ ] **Step 7: Create `ui/src/tokens/index.ts` for TS consumers**

```typescript
/**
 * Design token mirrors for use in TypeScript/JSX where `var(--j-*)` is awkward.
 * Keep values in sync with tokens/*.css — these are source-of-truth for runtime,
 * the CSS vars are source-of-truth for paint. A test verifies they match.
 */
export const colors = {
  bg: "#050508",
  surface: "rgba(255, 255, 255, 0.03)",
  surfaceHover: "rgba(255, 255, 255, 0.06)",
  border: "rgba(255, 255, 255, 0.06)",
  borderGlow: "rgba(0, 212, 255, 0.15)",
  cyan: "#00d4ff",
  cyanDim: "rgba(0, 212, 255, 0.6)",
  cyanGlow: "rgba(0, 212, 255, 0.12)",
  cyanStrong: "rgba(0, 212, 255, 0.85)",
  cyanSoft: "rgba(0, 212, 255, 0.35)",
  cyanWash: "rgba(0, 212, 255, 0.05)",
  amber: "#ffb800",
  green: "#00e676",
  red: "#ff3d57",
  offline: "#4a5568",
  offlineGlow: "rgba(74, 85, 104, 0.2)",
  text: "#e8eaed",
  textDim: "rgba(255, 255, 255, 0.4)",
  textMuted: "rgba(255, 255, 255, 0.2)",
} as const;

export const motion = {
  durationFast: 150,
  durationBase: 300,
  durationSlow: 600,
  easeOut: [0.2, 0.8, 0.2, 1] as const,
  easeInOut: [0.4, 0, 0.2, 1] as const,
  easeExpo: [0.16, 1, 0.3, 1] as const,
} as const;

export type ColorToken = keyof typeof colors;
```

- [ ] **Step 8: Write the failing test — verify CSS vars match TS mirror**

Create `ui/src/tokens/__tests__/tokens.test.ts`:

```typescript
import { describe, it, expect, beforeAll } from "vitest";
import { colors } from "../index";
import "../index.css";

describe("design tokens", () => {
  beforeAll(() => {
    // Ensure :root vars are present in jsdom
    document.documentElement.style.cssText = document.documentElement.style.cssText;
  });

  it("TS mirror stays in sync with CSS custom properties", () => {
    const root = getComputedStyle(document.documentElement);
    // Spot-check critical tokens — TS value must equal computed CSS value
    expect(root.getPropertyValue("--j-cyan").trim()).toBe(colors.cyan);
    expect(root.getPropertyValue("--j-bg").trim()).toBe(colors.bg);
    expect(root.getPropertyValue("--j-offline").trim()).toBe(colors.offline);
    expect(root.getPropertyValue("--j-red").trim()).toBe(colors.red);
  });

  it("new semantic tiers are defined", () => {
    const root = getComputedStyle(document.documentElement);
    expect(root.getPropertyValue("--j-cyan-strong").trim()).toBeTruthy();
    expect(root.getPropertyValue("--j-success").trim()).toBeTruthy();
    expect(root.getPropertyValue("--j-warning").trim()).toBeTruthy();
    expect(root.getPropertyValue("--j-offline").trim()).toBeTruthy();
  });
});
```

- [ ] **Step 9: Run the test — verify it fails with "No module" or token missing**

Run: `cd ui && npx vitest run src/tokens/__tests__/tokens.test.ts`
Expected: FAIL — either "cannot resolve ../index" or token values don't match (because `tokens/index.css` doesn't exist yet at time of first run).

- [ ] **Step 10: Modify `ui/src/index.css` to consume the new tokens**

Replace lines 1-21 of current `ui/src/index.css` (the `@import "tailwindcss"`, font import, and `:root { ... }` block) with:

```css
@import "tailwindcss";
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
@import "./tokens/index.css";
```

Leave the rest of `ui/src/index.css` (body styles, `.glass`, `.glow-text`, `.mono`, keyframes) intact. Those utilities stay here — they are project-specific compositions of the tokens, not tokens themselves.

- [ ] **Step 11: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/tokens/__tests__/tokens.test.ts`
Expected: PASS (2 tests green).

- [ ] **Step 12: Run TypeScript check — no regressions**

Run: `cd ui && npx tsc --noEmit`
Expected: exit 0, no errors.

- [ ] **Step 13: Smoke-test the dev server visually**

Run: `preview_start` with `ui-dev` configuration. Snapshot the `/` route.
Expected: background colour, sidebar, fonts render identically to before this chunk. No visual regression.

- [ ] **Step 14: Commit**

```bash
git add ui/src/tokens/ ui/src/index.css
git commit -m "feat(ui): extract design tokens into ui/src/tokens/ with TS mirror

- Split colours/typography/spacing/elevation/motion into dedicated files
- Add semantic tiers (strong/soft/wash/success/warning/danger/offline)
- TypeScript re-export for compile-time autocomplete
- prefers-reduced-motion: duration -> 0ms at token level
- Kept .glass / .glow-text / .mono in index.css (project-specific utilities)
- Zero visual regressions: existing var(--j-*) consumers unchanged"
```

---

## Chunk 2: Motion Primitives

**What:** Wrap Framer Motion (already a dependency, currently unused) in four small primitives that every surface can reach for. Each primitive reads motion tokens, respects `prefers-reduced-motion`, and exposes a minimal prop surface. This lets future plans write `<FadeSlideUp>…</FadeSlideUp>` instead of reinventing `motion.div` variants each time.

### Files

- Create: `ui/src/motion/usePrefersReducedMotion.ts`
- Create: `ui/src/motion/FadeSlideUp.tsx`
- Create: `ui/src/motion/ScaleHover.tsx`
- Create: `ui/src/motion/GlowPulse.tsx`
- Create: `ui/src/motion/NumberReveal.tsx`
- Create: `ui/src/motion/index.ts` (barrel)
- Test: `ui/src/motion/__tests__/FadeSlideUp.test.tsx`
- Test: `ui/src/motion/__tests__/NumberReveal.test.tsx`
- Test: `ui/src/motion/__tests__/usePrefersReducedMotion.test.ts`

### Tasks

- [ ] **Step 1: Write test for `usePrefersReducedMotion` hook**

Create `ui/src/motion/__tests__/usePrefersReducedMotion.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePrefersReducedMotion } from "../usePrefersReducedMotion";

function mockMatchMedia(matches: boolean) {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    media: "(prefers-reduced-motion: reduce)",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("usePrefersReducedMotion", () => {
  it("returns true when user prefers reduced motion", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(true);
  });

  it("returns false when user does not prefer reduced motion", () => {
    mockMatchMedia(false);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/motion/__tests__/usePrefersReducedMotion.test.ts`
Expected: FAIL — "Cannot find module '../usePrefersReducedMotion'".

- [ ] **Step 3: Implement `usePrefersReducedMotion`**

Create `ui/src/motion/usePrefersReducedMotion.ts`:

```typescript
import { useEffect, useState } from "react";

/**
 * Returns true when the user has requested reduced motion at the OS level.
 * Motion primitives short-circuit expensive animations when this is true.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduce, setReduce] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e: MediaQueryListEvent) => setReduce(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return reduce;
}
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/motion/__tests__/usePrefersReducedMotion.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Write test for `<FadeSlideUp>` primitive**

Create `ui/src/motion/__tests__/FadeSlideUp.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { FadeSlideUp } from "../FadeSlideUp";

describe("FadeSlideUp", () => {
  it("renders children", () => {
    render(<FadeSlideUp>hello</FadeSlideUp>);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("applies the data-motion attribute for debugging", () => {
    render(<FadeSlideUp>x</FadeSlideUp>);
    expect(screen.getByText("x").closest("[data-motion]")).not.toBeNull();
  });
});
```

- [ ] **Step 6: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/motion/__tests__/FadeSlideUp.test.tsx`
Expected: FAIL.

- [ ] **Step 7: Implement `<FadeSlideUp>`**

Create `ui/src/motion/FadeSlideUp.tsx`:

```typescript
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { motion as motionTokens } from "../tokens";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface FadeSlideUpProps {
  children: ReactNode;
  delay?: number;
  className?: string;
}

export function FadeSlideUp({ children, delay = 0, className }: FadeSlideUpProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <motion.div
      data-motion="fade-slide-up"
      className={className}
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduce ? 0 : motionTokens.durationBase / 1000,
        ease: motionTokens.easeOut,
        delay,
      }}
    >
      {children}
    </motion.div>
  );
}
```

- [ ] **Step 8: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/motion/__tests__/FadeSlideUp.test.tsx`
Expected: PASS.

- [ ] **Step 9: Implement `<ScaleHover>` (no test — trivial, covered by snapshot in Chunk 4 showcase)**

Create `ui/src/motion/ScaleHover.tsx`:

```typescript
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface ScaleHoverProps {
  children: ReactNode;
  scale?: number;
  className?: string;
  onClick?: () => void;
}

export function ScaleHover({ children, scale = 1.02, className, onClick }: ScaleHoverProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <motion.div
      data-motion="scale-hover"
      className={className}
      onClick={onClick}
      whileHover={reduce ? undefined : { scale }}
      whileTap={reduce ? undefined : { scale: 0.98 }}
      transition={{ duration: 0.15, ease: [0.2, 0.8, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}
```

- [ ] **Step 10: Implement `<GlowPulse>`**

Create `ui/src/motion/GlowPulse.tsx`:

```typescript
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface GlowPulseProps {
  children: ReactNode;
  color?: string;
  className?: string;
}

/**
 * Pulsing glow halo around children. Used to draw attention (active agent card,
 * incoming notification). Takes colour as CSS var string, defaults to cyan.
 */
export function GlowPulse({ children, color = "var(--j-cyan-glow)", className }: GlowPulseProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <motion.div
      data-motion="glow-pulse"
      className={className}
      style={{ position: "relative" }}
      animate={
        reduce
          ? undefined
          : {
              boxShadow: [
                `0 0 0 0 ${color}`,
                `0 0 0 12px transparent`,
              ],
            }
      }
      transition={reduce ? undefined : { duration: 2, repeat: Infinity, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
```

- [ ] **Step 11: Write test for `<NumberReveal>` primitive**

Create `ui/src/motion/__tests__/NumberReveal.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { NumberReveal } from "../NumberReveal";

describe("NumberReveal", () => {
  it("displays final value immediately when prefers-reduced-motion", () => {
    // jsdom defaults matchMedia to matches=false, need manual stub
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: q.includes("reduce"),
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    render(<NumberReveal value={42} />);
    expect(screen.getByTestId("number-reveal")).toHaveTextContent("42");
  });

  it("eventually reaches the target value", async () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: false,
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    render(<NumberReveal value={100} durationMs={50} />);
    await waitFor(() => {
      expect(screen.getByTestId("number-reveal")).toHaveTextContent("100");
    }, { timeout: 500 });
  });
});
```

- [ ] **Step 12: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/motion/__tests__/NumberReveal.test.tsx`
Expected: FAIL.

- [ ] **Step 13: Implement `<NumberReveal>`**

Create `ui/src/motion/NumberReveal.tsx`:

```typescript
import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface NumberRevealProps {
  value: number;
  durationMs?: number;
  format?: (n: number) => string;
  className?: string;
}

/**
 * Counts up from 0 to `value` over `durationMs`. Snaps to final value when
 * prefers-reduced-motion is set. Used in Dashboard tiles and status counters.
 */
export function NumberReveal({
  value,
  durationMs = 600,
  format = (n) => n.toLocaleString(),
  className,
}: NumberRevealProps) {
  const reduce = usePrefersReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out-cubic
      setDisplay(Math.round(eased * value));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    };
  }, [value, durationMs, reduce]);

  return (
    <span data-testid="number-reveal" className={className}>
      {format(display)}
    </span>
  );
}
```

- [ ] **Step 14: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/motion/__tests__/NumberReveal.test.tsx`
Expected: PASS.

- [ ] **Step 15: Create `ui/src/motion/index.ts` barrel**

```typescript
export { FadeSlideUp } from "./FadeSlideUp";
export { ScaleHover } from "./ScaleHover";
export { GlowPulse } from "./GlowPulse";
export { NumberReveal } from "./NumberReveal";
export { usePrefersReducedMotion } from "./usePrefersReducedMotion";
```

- [ ] **Step 16: Run full motion test suite + tsc**

Run:
```bash
cd ui && npx vitest run src/motion/
cd ui && npx tsc --noEmit
```
Expected: all motion tests PASS; tsc exit 0.

- [ ] **Step 17: Commit**

```bash
git add ui/src/motion/
git commit -m "feat(ui): motion primitives with prefers-reduced-motion support

FadeSlideUp / ScaleHover / GlowPulse / NumberReveal wrap Framer Motion
with token-driven durations and auto-respect prefers-reduced-motion.
NumberReveal uses requestAnimationFrame with ease-out-cubic.

Tests cover: reduced-motion short-circuit, final-value snap, lifecycle."
```

---

## Chunk 3: HUD Component Primitives

**What:** Four atomic HUD-flavoured components that consume the tokens + motion primitives. Each is ~40-80 LoC. These are what onboarding/settings/agent-store plans will compose — we build them once here, use them everywhere after.

### Files

- Create: `ui/src/components/hud/HexFrame.tsx`
- Create: `ui/src/components/hud/PulseOrb.tsx`
- Create: `ui/src/components/hud/HudDivider.tsx`
- Create: `ui/src/components/hud/ScanLineBg.tsx`
- Create: `ui/src/components/hud/index.ts`
- Test: `ui/src/components/hud/__tests__/HexFrame.test.tsx`
- Test: `ui/src/components/hud/__tests__/PulseOrb.test.tsx`
- Test: `ui/src/components/hud/__tests__/HudDivider.test.tsx`

### Tasks

- [ ] **Step 1: Write test for `<HexFrame>`**

Create `ui/src/components/hud/__tests__/HexFrame.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HexFrame } from "../HexFrame";

describe("HexFrame", () => {
  it("renders children inside a clip-path container", () => {
    render(<HexFrame><span>hello</span></HexFrame>);
    const inner = screen.getByText("hello");
    const frame = inner.closest("[data-hud='hex-frame']") as HTMLElement;
    expect(frame).not.toBeNull();
    expect(frame.style.clipPath).toContain("polygon");
  });

  it("applies `active` glow when prop is true", () => {
    render(<HexFrame active><span>x</span></HexFrame>);
    const frame = screen.getByText("x").closest("[data-hud='hex-frame']") as HTMLElement;
    expect(frame.getAttribute("data-active")).toBe("true");
  });
});
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/components/hud/__tests__/HexFrame.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement `<HexFrame>`**

Create `ui/src/components/hud/HexFrame.tsx`:

```typescript
import type { ReactNode } from "react";

interface HexFrameProps {
  children: ReactNode;
  active?: boolean;
  className?: string;
}

/**
 * Hex-clipped container. Used for primary-action cards, agent tiles, hero
 * frames. Active state adds a cyan glow border. Corners carved via clip-path.
 */
export function HexFrame({ children, active = false, className }: HexFrameProps) {
  const corner = "14px";
  return (
    <div
      data-hud="hex-frame"
      data-active={active}
      className={className}
      style={{
        clipPath: `polygon(
          ${corner} 0,
          calc(100% - ${corner}) 0,
          100% ${corner},
          100% calc(100% - ${corner}),
          calc(100% - ${corner}) 100%,
          ${corner} 100%,
          0 calc(100% - ${corner}),
          0 ${corner}
        )`,
        background: active ? "var(--j-surface-hover)" : "var(--j-surface)",
        border: `1px solid ${active ? "var(--j-border-glow)" : "var(--j-border)"}`,
        boxShadow: active ? "var(--j-elev-2)" : "var(--j-elev-0)",
        transition: "all var(--j-duration-base) var(--j-ease-in-out)",
      }}
    >
      {children}
    </div>
  );
}
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/components/hud/__tests__/HexFrame.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write test for `<PulseOrb>`**

Create `ui/src/components/hud/__tests__/PulseOrb.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PulseOrb } from "../PulseOrb";

describe("PulseOrb", () => {
  it("renders with default size and cyan state", () => {
    render(<PulseOrb />);
    const orb = screen.getByTestId("pulse-orb");
    expect(orb.getAttribute("data-state")).toBe("active");
  });

  it("applies offline state when active={false}", () => {
    render(<PulseOrb active={false} />);
    const orb = screen.getByTestId("pulse-orb");
    expect(orb.getAttribute("data-state")).toBe("offline");
  });

  it("supports danger status color", () => {
    render(<PulseOrb status="danger" />);
    const orb = screen.getByTestId("pulse-orb");
    expect(orb.getAttribute("data-status")).toBe("danger");
  });
});
```

- [ ] **Step 6: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/components/hud/__tests__/PulseOrb.test.tsx`
Expected: FAIL.

- [ ] **Step 7: Implement `<PulseOrb>`**

Create `ui/src/components/hud/PulseOrb.tsx`:

```typescript
import { usePrefersReducedMotion } from "../../motion/usePrefersReducedMotion";

type Status = "info" | "success" | "warning" | "danger";

interface PulseOrbProps {
  active?: boolean;
  status?: Status;
  size?: number;
  className?: string;
}

const STATUS_COLORS: Record<Status, { core: string; glow: string }> = {
  info: { core: "var(--j-cyan)", glow: "var(--j-cyan-glow)" },
  success: { core: "var(--j-success)", glow: "var(--j-success-glow)" },
  warning: { core: "var(--j-warning)", glow: "var(--j-warning-glow)" },
  danger: { core: "var(--j-danger)", glow: "var(--j-danger-glow)" },
};

/**
 * Small pulsing reactor-style indicator. Shrunk version of ArcReactor's core.
 * Use anywhere you need "something is happening here" — status bar, nightstand,
 * voice-mode entry point. `active` drives whether it pulses or dims.
 */
export function PulseOrb({
  active = true,
  status = "info",
  size = 12,
  className,
}: PulseOrbProps) {
  const reduce = usePrefersReducedMotion();
  const colors = active ? STATUS_COLORS[status] : { core: "var(--j-offline)", glow: "var(--j-offline-glow)" };
  return (
    <span
      data-testid="pulse-orb"
      data-state={active ? "active" : "offline"}
      data-status={status}
      className={className}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${colors.core} 0%, ${colors.core}44 60%, transparent 100%)`,
        boxShadow: active ? `0 0 ${size}px ${colors.glow}` : "none",
        animation: active && !reduce ? "pulse-orb 2s ease-in-out infinite" : "none",
      }}
    />
  );
}
```

- [ ] **Step 8: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/components/hud/__tests__/PulseOrb.test.tsx`
Expected: PASS.

- [ ] **Step 9: Add `pulse-orb` keyframe to `ui/src/index.css`**

Append to `ui/src/index.css` (after the existing keyframes section):

```css
@keyframes pulse-orb {
  0%, 100% { transform: scale(1); opacity: 0.85; }
  50% { transform: scale(1.15); opacity: 1; }
}
```

- [ ] **Step 10: Write test for `<HudDivider>`**

Create `ui/src/components/hud/__tests__/HudDivider.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HudDivider } from "../HudDivider";

describe("HudDivider", () => {
  it("renders a labelled divider", () => {
    render(<HudDivider label="Section" />);
    expect(screen.getByText("SECTION")).toBeInTheDocument();
  });

  it("renders without label when omitted", () => {
    render(<HudDivider />);
    expect(screen.queryByText(/./)).toBeNull();
  });
});
```

- [ ] **Step 11: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/components/hud/__tests__/HudDivider.test.tsx`
Expected: FAIL.

- [ ] **Step 12: Implement `<HudDivider>`**

Create `ui/src/components/hud/HudDivider.tsx`:

```typescript
interface HudDividerProps {
  label?: string;
  className?: string;
}

/**
 * Horizontal rule with glow + optional ALL-CAPS label in the middle.
 * Used to divide Dashboard sections and Settings groups.
 */
export function HudDivider({ label, className }: HudDividerProps) {
  const lineStyle = {
    flex: 1,
    height: 1,
    background: "linear-gradient(90deg, transparent, var(--j-border-glow), transparent)",
  };
  return (
    <div
      data-hud="hud-divider"
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--j-space-3)",
        width: "100%",
      }}
    >
      <span style={lineStyle} />
      {label !== undefined && (
        <span
          style={{
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-hud)",
            color: "var(--j-text-dim)",
            textTransform: "uppercase",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
      )}
      <span style={lineStyle} />
    </div>
  );
}
```

- [ ] **Step 13: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/components/hud/__tests__/HudDivider.test.tsx`
Expected: PASS.

- [ ] **Step 14: Implement `<ScanLineBg>` (no dedicated test — purely visual, covered by Chunk 4 showcase)**

Create `ui/src/components/hud/ScanLineBg.tsx`:

```typescript
interface ScanLineBgProps {
  opacity?: number;
  className?: string;
}

/**
 * Subtle horizontal scan-line overlay — CRT-reminiscent atmosphere.
 * Place as first child of a relatively-positioned container. Off by default
 * under prefers-reduced-motion (static pattern, no flicker).
 */
export function ScanLineBg({ opacity = 0.03, className }: ScanLineBgProps) {
  return (
    <div
      data-hud="scan-line-bg"
      className={className}
      aria-hidden="true"
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        backgroundImage:
          "repeating-linear-gradient(0deg, rgba(255,255,255,0.6) 0, rgba(255,255,255,0.6) 1px, transparent 1px, transparent 3px)",
        opacity,
        mixBlendMode: "overlay",
      }}
    />
  );
}
```

- [ ] **Step 15: Create `ui/src/components/hud/index.ts` barrel**

```typescript
export { HexFrame } from "./HexFrame";
export { PulseOrb } from "./PulseOrb";
export { HudDivider } from "./HudDivider";
export { ScanLineBg } from "./ScanLineBg";
```

- [ ] **Step 16: Run full HUD test suite + tsc**

Run:
```bash
cd ui && npx vitest run src/components/hud/
cd ui && npx tsc --noEmit
```
Expected: all HUD tests PASS; tsc exit 0.

- [ ] **Step 17: Commit**

```bash
git add ui/src/components/hud/ ui/src/index.css
git commit -m "feat(ui): HUD component primitives (HexFrame/PulseOrb/HudDivider/ScanLineBg)

Four atomic components consumed by every surface redesign to come.
All respect design tokens, prefers-reduced-motion, and expose minimal
prop surfaces. PulseOrb supports info/success/warning/danger statuses.

pulse-orb keyframe added to index.css. Unit tests for HexFrame/PulseOrb/
HudDivider cover active-state and label-present branches."
```

---

## Chunk 4: Showcase Page + Accessibility Test

**What:** A dev-only `/showcase` surface that renders every token and primitive in one place — living documentation plus a visual smoke-test surface. Add an automated a11y test that verifies `prefers-reduced-motion` is actually respected. This is the artefact the next plan authors use to reach for primitives without reading source.

### Files

- Create: `ui/src/components/Showcase/Showcase.tsx`
- Create: `ui/src/components/Showcase/__tests__/Showcase.test.tsx`
- Modify: `ui/src/stores/appStore.ts` — add `"showcase"` to the `mode` type union
- Modify: `ui/src/components/Layout/Sidebar.tsx` — add a dev-only nav button for showcase
- Modify: `ui/src/App.tsx` — render `<Showcase />` when `mode === "showcase"`
- Test: `ui/src/components/Showcase/__tests__/reducedMotion.test.tsx`

### Tasks

- [ ] **Step 1: Write test for showcase render + primitive presence**

Create `ui/src/components/Showcase/__tests__/Showcase.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Showcase } from "../Showcase";

describe("Showcase", () => {
  it("renders section headings for tokens / motion / hud", () => {
    render(<Showcase />);
    expect(screen.getByText(/colors/i)).toBeInTheDocument();
    expect(screen.getByText(/motion/i)).toBeInTheDocument();
    expect(screen.getByText(/hud primitives/i)).toBeInTheDocument();
  });

  it("mounts at least one PulseOrb", () => {
    render(<Showcase />);
    expect(screen.getAllByTestId("pulse-orb").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd ui && npx vitest run src/components/Showcase/__tests__/Showcase.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement `<Showcase>`**

Create `ui/src/components/Showcase/Showcase.tsx`:

```typescript
import { HexFrame, HudDivider, PulseOrb, ScanLineBg } from "../hud";
import { FadeSlideUp, GlowPulse, NumberReveal, ScaleHover } from "../../motion";
import { colors } from "../../tokens";

export function Showcase() {
  return (
    <div style={{ padding: "var(--j-space-8)", overflowY: "auto", width: "100%", height: "100%" }}>
      <h1 style={{ fontFamily: "var(--j-font-mono)", letterSpacing: "var(--j-tracking-hud)", color: "var(--j-cyan)" }}>
        ИНТЕРФЕЙС — SHOWCASE
      </h1>

      <HudDivider label="Colors" />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "var(--j-space-3)", margin: "var(--j-space-4) 0" }}>
        {Object.entries(colors).map(([name, value]) => (
          <div key={name} style={{ background: value, padding: "var(--j-space-3)", borderRadius: "var(--j-radius-md)", fontSize: "var(--j-text-xs)" }}>
            <code style={{ mixBlendMode: "difference", color: "white" }}>{name}</code>
          </div>
        ))}
      </div>

      <HudDivider label="Motion" />
      <div style={{ display: "flex", gap: "var(--j-space-4)", flexWrap: "wrap", margin: "var(--j-space-4) 0" }}>
        <FadeSlideUp><HexFrame><div style={{ padding: "var(--j-space-4)" }}>FadeSlideUp</div></HexFrame></FadeSlideUp>
        <ScaleHover><HexFrame><div style={{ padding: "var(--j-space-4)" }}>ScaleHover (hover me)</div></HexFrame></ScaleHover>
        <GlowPulse><HexFrame active><div style={{ padding: "var(--j-space-4)" }}>GlowPulse</div></HexFrame></GlowPulse>
        <div style={{ padding: "var(--j-space-4)", border: "1px solid var(--j-border)", borderRadius: "var(--j-radius-md)" }}>
          <NumberReveal value={42} /> agents
        </div>
      </div>

      <HudDivider label="HUD Primitives" />
      <div style={{ display: "flex", gap: "var(--j-space-4)", alignItems: "center", margin: "var(--j-space-4) 0" }}>
        <PulseOrb /> info
        <PulseOrb status="success" /> success
        <PulseOrb status="warning" /> warning
        <PulseOrb status="danger" /> danger
        <PulseOrb active={false} /> offline
      </div>

      <div style={{ position: "relative", height: 120, border: "1px solid var(--j-border)", borderRadius: "var(--j-radius-md)", overflow: "hidden", margin: "var(--j-space-4) 0" }}>
        <ScanLineBg />
        <div style={{ padding: "var(--j-space-4)" }}>ScanLineBg overlay demo</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `cd ui && npx vitest run src/components/Showcase/__tests__/Showcase.test.tsx`
Expected: PASS.

- [ ] **Step 5: Add `"showcase"` to appStore mode union**

Modify `ui/src/stores/appStore.ts`. Locate the `type Mode` or equivalent union. Add `"showcase"` to it. Also ensure the default mode is unchanged.

- [ ] **Step 6: Wire up routing in App.tsx**

Modify `ui/src/App.tsx`. Below the existing `{mode === "settings" && <Settings />}` line, add:

```tsx
{mode === "showcase" && <Showcase />}
```

Add the import at the top:
```tsx
import { Showcase } from "./components/Showcase/Showcase";
```

- [ ] **Step 7: Add dev-only Showcase button to Sidebar**

Modify `ui/src/components/Layout/Sidebar.tsx`. After the Settings button (⚙), add:

```tsx
{import.meta.env.DEV && (
  <SidebarBtn
    icon="◈"
    label="Showcase"
    active={mode === "showcase"}
    onClick={() => setMode("showcase")}
  />
)}
```

(Adapt the JSX to the existing button pattern in the file — it may use different prop names or a map. Don't invent a new component, mirror whatever exists.)

- [ ] **Step 8: Write the reduced-motion assertion test**

Create `ui/src/components/Showcase/__tests__/reducedMotion.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PulseOrb } from "../../hud";

describe("prefers-reduced-motion", () => {
  it("disables PulseOrb animation when user prefers reduced motion", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: q.includes("reduce"),
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    const { getByTestId } = render(<PulseOrb />);
    const orb = getByTestId("pulse-orb");
    expect(orb.style.animation).toBe("none");
  });
});
```

- [ ] **Step 9: Run the reduced-motion test — verify it passes**

Run: `cd ui && npx vitest run src/components/Showcase/__tests__/reducedMotion.test.tsx`
Expected: PASS (PulseOrb already implements the short-circuit in Chunk 3).

- [ ] **Step 10: Start preview + smoke-test the showcase visually**

Run: `preview_start` with `ui-dev`.
Then in the preview, switch mode to `"showcase"` via eval:
```javascript
(await import('/src/stores/appStore.ts')).useAppStore.setState({ mode: 'showcase' })
```
Take screenshot. Verify: colour swatches, motion examples animate, PulseOrbs render in all 4 statuses + offline, ScanLineBg overlay visible.

- [ ] **Step 11: Run full tsc + vitest**

Run:
```bash
cd ui && npx tsc --noEmit
cd ui && npx vitest run
```
Expected: tsc exit 0; all UI tests PASS.

- [ ] **Step 12: Commit**

```bash
git add ui/src/components/Showcase/ ui/src/components/Layout/Sidebar.tsx ui/src/stores/appStore.ts ui/src/App.tsx
git commit -m "feat(ui): /showcase surface — living documentation of tokens and primitives

Dev-only mode (gated by import.meta.env.DEV) that renders every token
swatch, motion primitive, and HUD component in one place. Used as both
visual smoke-test and onboarding reference for the four surface
redesigns consuming this foundation.

Includes automated assertion that prefers-reduced-motion disables
PulseOrb animation — the canary for all motion primitives."
```

---

## Chunk 5: Migrate Existing Surfaces

**What:** Prove the token system survives contact with reality by migrating three existing surfaces — `ArcReactor`, `Sidebar`, `ChatInput` — off hardcoded colours and onto tokens. Visual regression budget: zero intentional change. If migration requires behavioural tweaks, they go in a follow-up plan, not here.

### Files

- Modify: `ui/src/components/Avatar/ArcReactor.tsx` — replace hardcoded `#00d4ff`, `rgba(0, 212, 255, *)`, `#ffb800`, `#00e676`, `#4a5568` with token references.
- Modify: `ui/src/components/Layout/Sidebar.tsx` — replace inline hex/rgba with tokens.
- Modify: `ui/src/components/Chat/ChatInput.tsx` — same.

### Tasks

- [ ] **Step 1: Start preview + capture baseline screenshot**

Run `preview_start ui-dev`. Take screenshot of the focus mode (ArcReactor visible). Save to `/tmp/before-arc.png` via preview_screenshot (the tool writes the image to stdout; confirm we have the baseline captured).

- [ ] **Step 2: Migrate `ArcReactor.tsx` colours to tokens**

In `ui/src/components/Avatar/ArcReactor.tsx`, replace the `STATE_COLORS` record:

```typescript
const STATE_COLORS: Record<string, { core: string; glow: string; speed: number }> = {
  idle: { core: "var(--j-cyan)", glow: "var(--j-cyan-glow)", speed: 1 },
  listening: { core: "var(--j-cyan)", glow: "var(--j-cyan-soft)", speed: 2.5 },
  thinking: { core: "var(--j-amber)", glow: "var(--j-warning-glow)", speed: 4 },
  speaking: { core: "var(--j-green)", glow: "var(--j-success-glow)", speed: 1.5 },
  idle_active: { core: "var(--j-cyan)", glow: "var(--j-cyan-soft)", speed: 1.6 },
  offline: { core: "var(--j-offline)", glow: "var(--j-offline-glow)", speed: 0.3 },
};
```

Note: token names differ slightly from the old rgba values. `rgba(0, 212, 255, 0.5)` → `--j-cyan-soft` (0.35). This is a *controlled* shift, not arbitrary. Check the screenshot after — if the shift is too visible, dial the tokens instead of reverting the component.

- [ ] **Step 3: TypeScript + visual compare**

Run: `cd ui && npx tsc --noEmit` — exit 0.
Preview reload. Compare with baseline screenshot. If any state looks materially different, adjust token values in `tokens/colors.css`, not the component.

- [ ] **Step 4: Migrate `Sidebar.tsx`**

Read `ui/src/components/Layout/Sidebar.tsx`. For every hardcoded colour (any literal `#......`, `rgb()`, `rgba()`), either:
- Replace with `var(--j-*)` if a token matches
- If no token matches, stop — add a new token to `colors.css` with a semantic name, then use it.

(Leave styles that are already using `var(--j-*)` alone. Replace only literals.)

- [ ] **Step 5: TypeScript + visual compare for Sidebar**

Same as Step 3.

- [ ] **Step 6: Migrate `ChatInput.tsx`**

Same approach as Sidebar. Pay attention to the mic button colour states (active/inactive).

- [ ] **Step 7: Run full test suite + tsc**

Run:
```bash
cd ui && npx tsc --noEmit
cd ui && npx vitest run
.venv/Scripts/python.exe -m pytest tests/kernel/
```
Expected: all green. (Backend tests run because config changes touched the voice pipeline earlier in this session — sanity check nothing regressed.)

- [ ] **Step 8: Visual final sweep**

Preview the full app:
- Focus mode (ArcReactor)
- Dashboard mode
- Agent Panel mode
- Settings mode
- /showcase

Any colour looks off? Revert the specific migration, leave a `// TODO(tokens)` comment, move on. Do not block the plan on pixel-perfection — the goal is *mechanical* replacement of literals with tokens, not a redesign.

- [ ] **Step 9: Commit**

```bash
git add ui/src/components/Avatar/ArcReactor.tsx ui/src/components/Layout/Sidebar.tsx ui/src/components/Chat/ChatInput.tsx ui/src/tokens/colors.css
git commit -m "refactor(ui): migrate ArcReactor/Sidebar/ChatInput to design tokens

Replaces hardcoded hex/rgba with var(--j-*) references. Visual intent
preserved; minor shade shifts (e.g. cyan-soft at 0.35 vs hardcoded 0.5)
are accepted as part of the token tier definition.

No behavioural changes. Follow-up plans can now redesign these surfaces
without touching raw colour values."
```

---

## Success Criteria (whole plan)

- `ui/src/tokens/` exists with 5 CSS files + TS mirror; index.css consumes them.
- `ui/src/motion/` exposes 4 primitives, each tested, all respecting `prefers-reduced-motion`.
- `ui/src/components/hud/` exposes 4 primitives, each tested.
- `/showcase` surface renders all of the above in one page, reachable via the Sidebar dev button.
- `ArcReactor`, `Sidebar`, `ChatInput` contain zero hardcoded colour literals.
- `npx tsc --noEmit` exit 0 at the end of every chunk.
- `npx vitest run` all green at the end of every chunk.
- Backend test suite (`pytest tests/kernel/`) unchanged — this plan does not touch Python.
- Plan-level commits: 5 (one per chunk).

## Risks Revisited

| Risk | Mitigation |
|------|------------|
| Over-engineering — tokens for things never used | In scope: only what existing code already contains + items listed in stub. Nothing speculative. |
| Visual drift on migration (Chunk 5) | Baseline screenshot before, compare after. Dial tokens, never revert to literals. |
| Framer Motion bundle bloat | Only import what we use. Four primitives, no layout-motion. Bundle check: run `vite build` and verify gzipped size of `framer-motion` chunk < 40kb. |
| a11y regression — hidden scan-lines + glow fatigue | `prefers-reduced-motion` disables orb pulse + motion primitive transitions. `ScanLineBg` is aria-hidden. A11y test enforces the orb branch. |
| Tailwind 4 + custom CSS conflict | `@import "tailwindcss"` stays first. Token vars are CSS custom properties — orthogonal to Tailwind utilities. No conflict by design. |

## What's Next After This Ships

Roadmap plans that now become unblocked (and should explicitly reference this plan's primitives):
- `2026-04-27-onboarding-flow` — uses FadeSlideUp, HexFrame, PulseOrb, NumberReveal.
- `2026-04-28-settings-ui` — uses HudDivider for grouping, HexFrame for privileged toggles, tokens throughout.
- `2026-04-30-agent-store-v2` — uses HexFrame for agent tiles, PulseOrb for install-status, ScanLineBg for hero.
- `2026-05-01-tsifrovoy-status` — uses all four primitives heavily; NumberReveal is the centrepiece.

Estimate: 2-3 days solo. Chunks are independent once Chunk 1 lands — can be parallelised across sessions if a second dev joins.
