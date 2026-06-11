# Build round 2026-06-11 — fixes + curated storefront (as-built)

> **Status:** executed (approved «го» 2026-06-10 evening). This doc records scope,
> decisions and the follow-up backlog produced by the round.

## Scope (approved)

1. **fix(ui) `c0e4825`** — layoutId tab pill deadlocked app-level `AnimatePresence
   mode="wait"`: leaving Agent Skills after a tab switch left the old view at
   opacity 0 and no mode could mount (black screen, alive sidebar). Pill → plain
   div; constraint documented in App.tsx. Root-caused live in dev (isolation:
   nested AnimatePresence innocent, layoutId necessary & sufficient).
2. **fix(backend) `278aeae`** — single-instance lock held as an exclusive OS lock
   on an fd kept open for the process lifetime (msvcrt/fcntl). Kills the
   PID-reuse restart lottery (shell hard-kills backend → stale PID file → silent
   `sys.exit(0)` → red dot / Failed to fetch). Refused start now logs a breadcrumb.
   Tests: `tests/kernel/test_entry_lock.py` (4).
3. **fix(voice) `eeae605`** — SentenceBuffer merges closed sentences until
   `min_chars=40`: F5's ~2 s fixed per-call cost made short sentences (15 chars →
   1.0 s audio in 2.18 s) synthesize slower than playback → audible gap at
   periods. Tests updated: sentence_buffer (15), remote_pipeline_tts (5).
4. **feat(ui) `63b6b0d`** — Agent Store → curated storefront (plan B):
   life categories, RU benefit-first cards, hero «Создай голосом», built-in
   agents enable in 1 click, anthropic doc-skills install by source ref,
   «нужен ключ» plain-RU setup dialogs, Community tab (kali source) with
   «работает везде» interop badge, dev catalog intact behind «Для продвинутых».
5. **feat(ui) `c21e792`** — kernel-offline RU banner (3 s grace, auto-hide),
   RU sidebar tooltips, version 0.1.0 → 0.2.0-beta (ui + tauri, BLD-4).

## Delegated decisions (researched, then decided)

- **«Создать голосом» placement:** BOTH a hero tile (first thing in the store —
  creation is the product's headline action) and the small header button
  (persistent affordance). Standard store-front pattern: hero for discovery,
  toolbar for return visits.
- **Categories v1:** Напоминания и списки · Здоровье · Дом · Деньги · Новости и
  погода · Общение · Документы · Сообщество. Editable in `curated.ts` without
  touching components.
- **Starting content:** 14 built-in agents (RU-wrapped; dev/infra agents like
  coding/github/system excluded per anti-pivot) + 4 anthropic document skills =
  the store is NEVER empty, fully offline-capable for the agent part.
- **Key setup v1 = guidance, not a key vault:** the dialog explains in plain RU
  where to get the key (BotFather etc.) and deep-links to Settings. A unified
  per-skill config store is future work (see backlog #4).

## Verification done

- Dev preview: storefront renders; categories filter; «Включить» → «Работает»
  (weather agent, real backend); setup dialog steps; Community graceful empty
  state; «Для продвинутых» view mounts. `tsc -b` exit 0; targeted pytest 24/24.
- Catalog list/install/sources are Rust-:3006 routes — verified post-swap in the
  installed app, not in dev (no Rust shell there).

## Known constraints / notes

- `VasilyKolbenev/kali-skills` is 404 (not created yet): Community tab shows the
  invite empty state until the repo exists. **Action for Vasily: create the
  public repo** (the publish flow already targets it).
- Installed-app Showcase mystery: bundle of 13:25 compiles the devOnly filter
  correctly, yet the installed app showed Showcase — resolved by this round's
  fresh desktop build (devOnly committed since 06-01); re-check post-swap.
- entry.py pre-existing ruff E402/I001 are intentional (freeze_support before
  imports) — left untouched.

## Next-round backlog (best-practice pass, prioritized)

| # | Item | Why | Size |
|---|------|-----|------|
| 1 | **(C) Agent statuses** «Работает/Остановлен/Нужна настройка» + life-dashboard permission grant flow (its denial spams the log every 30 s) | The opaque Start/Stop is the biggest remaining non-tech wall; permission denials are invisible | M |
| 2 | **(#2) Canvas widgets clickable** (expand/modal) | Agreed UX item from the live test | S |
| 3 | **TTS prefetch**: synthesize sentence N+1 while N plays (producer-consumer queue) | Finishes the gap fix; min_chars merge only narrows the window | M |
| 4 | **Unified skill config/keys store**: skills declare needed keys; Settings renders fields; store cards flip «нужен ключ» → «настроено» automatically | Turns setup guidance into a real 2-minute flow; unlocks (C)'s «Нужна настройка» state | M |
| 5 | **Bundle vocos+Whisper as real files** + `HF_HUB_OFFLINE` | Offline friend-install (UGC loop) currently re-downloads from HF after /MIR restage | M |
| 6 | **TTS prewarm hardening** (transformers.pipeline ImportError → first synth 30-50 s) + «Джарвис готовится…» first-use state in UI | First-run impression for friends | S–M |
| 7 | **Wake-word feedback**: earcon + explicit «слушаю» indicator; reconsider the 3 s listen timeout (silent reset reads as «не услышал») | Voice-UX best practice: every state change must be perceivable | S |
| 8 | **Create `kali-skills` repo + publish e2e** (then: interop badge content real) | Community tab + UGC pitch go live | S (Vasily) + S |
| 9 | **SEC-2 tail**: token auth on mutating :3006 routes for LAN exposure | Before un-trusted-network distribution | M |
| 10 | **Single-source version** (read app version from tauri config at build) | Prevents BLD-4 recurring | S |
| 11 | **DEV-1**: isolate ML/audio tests into subprocess (pytest native AV) | Unblocks full-suite CI | M |
| 12 | Audit batch D leftovers (KER-4/5, UI-6..9, MOB-7..12, RUS-1..4, BLD-5/6/7/9) | Hygiene | M–L |

Recommended next round: 1 + 2 + 4 (one coherent UX continuation), with 5 + 6
as the parallel «friend-install hardening» round.
