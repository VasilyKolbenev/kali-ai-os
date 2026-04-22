# Holographic Design Tokens — Plan Stub

> Status: STUB. Создан 2026-04-22. Full detail пишется перед execution.

**Goal:** Единый визуальный identity-pass в стиле JARVIS HUD — токены, анимации, wireframe-motifs. Pre-requirement для всех следующих surface-redesigns, чтобы Agent Store v2 и Цифровой статус изначально шли в новом стиле.

**Level:** 1 + cherry-pick from Level 2 (восходя в Level 3 после 100+ active users).

## In scope

### Design tokens (CSS variables)
- Цветовая палитра Stark: primary `#00D4FF` (cyan arc), accent `#1DE9B6` (green status), danger `#FF1744`, glow shadows для каждого
- Typography scale — монoshрифт (JetBrains Mono / IBM Plex Mono) для metadata/numbers
- Spacing, radii, opacity tiers
- Elevation system с glow-shadows вместо классических drop-shadows
- Scan-line overlay (SVG pattern, opacity 0.03)

### Motion system
- Framer Motion обёртки для standard transitions (slide-up + fade, scale-hover, glow-pulse)
- Number reveal — counters rolling up при mount
- Voice-pulse — orb-indicator при активном mic (keyframe animation)
- Boot sequence helper — для onboarding и first-app-start

### Component tokens
- `<HexFrame>` — hex-клип для важных карточек (агенты, hero tiles)
- `<PulseOrb>` — центральный reactor-style indicator (используется в Цифровом статусе и voice mode)
- `<HudDivider>` — horizontal rule с glow + side-ticks
- `<ScanLineBg>` — subtle CRT-fading overlay (opt-out в accessibility)

### Vocab (anti-licensing)
- Используем "Ядро KALI" (не "Arc Reactor")
- "Интерфейс" (не "HUD" буквально)
- "Контур" (не "Mark XLII")

## Out of scope

- 3D голограммы (Level 3 — после stability proof)
- Sound design (отложено — не все users хотят звуки)
- Full shader-based waveform (отдельный план когда voice mode станет primary)

## Risks

- **Accessibility:** `prefers-reduced-motion` обязан отключать все анимации кроме progress indicators
- **Performance:** scan-line + glows = +~5% GPU budget. Опция "low-motion" в settings.
- **Overuse:** если в каждую кнопку встраивать glow, получится casino. Discipline: glow только на primary actions + active states.

## Dependencies

- None — это foundation layer

## Success criteria

- Design tokens live in `ui/src/tokens/` (или `theme/`) as single source of truth
- Storybook/showcase page с визуальными examples каждого токена
- `prefers-reduced-motion` respected (automated a11y test)
- Measured FPS ≥ 55 на low-end laptop (Intel integrated GPU baseline)
- 3 существующих surfaces (Agent Store, Dashboard, Chat) прогнаны через новые токены без визуальных regressions

## Estimate

2-3 дня соло. Параллельно с voice-builder-pilot можно начинать — не трогает backend.

## What's next after this ships

Все surface-redesigns идут **после этого** и используют токены сразу (не переделывать дважды):
- onboarding-flow
- settings-ui
- agent-store-v2
- цифровой-статус
