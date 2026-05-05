# Proactive KALI v1 — Voice-first ambient intelligence

> Status: design spec, draft v1. Created 2026-05-05.
> Roadmap slot: Tier 2 #10.5 (between Agent Store v2 and Rust Phase 5). Estimated 5-7 days.
> Driven by: Anthropic Orbit positioning (May 2026) + KALI's existing Daily Briefing primitive.

## One-line summary

Move KALI from reactive ("ask, get answer") to proactive ("KALI tells you what matters") via three small features built on existing primitives — without losing the non-tech voice-first identity. Direct counter to Anthropic Orbit's text dashboards.

## Goal

After this spec ships, the user experience changes from:
- **Before:** open KALI → type or speak query → get answer → close.
- **After:** wake up → KALI greets with morning brief (voice) → during day, agents push relevant alerts (OS tray + voice for important) → after pattern detected, KALI suggests automation ("я заметил ты часто X — создать агента?").

The user does not configure anything. Defaults work. Settings are minimal.

## Vision alignment

KALI's proactive layer must **stay voice-first** and **non-tech-friendly**. Anthropic Orbit covers the proactive thesis for tech-audience text dashboards (`memory/project_competition.md` Competitor 3). KALI's slot: voice ambient intelligence for non-tech.

**Anti-pivot rule (binding):** No dev/design integrations (GitHub/Figma/IDE) in this spec. Stay in voice + OS native + KALI's existing agent ecosystem.

## Existing primitives (already shipped — we're amplifying, not building from scratch)

Backend:
- `kernel/main.py` — Daily Briefing on first `/chat` of day. Returns greeting + weather + active agents + tasks count.
- `kernel/skill_templates/notifier/` — trigger-based push (e.g., "biточкоин upal на 5%").
- `kernel/skill_templates/monitor/` — periodic check + alert.
- `kernel/scheduler.py` — generic cron jobs (already runs water-tracker every 2h).
- WebSocket event bus (Phase 2 SHIPPED) — for live UI updates.
- TTS pipeline (`kernel/voice/tts_router.py`) — F5 + ElevenLabs fallback.
- Auto-load agents at startup — calendar/weather/system/tasks default.

Frontend:
- `useBuilderStore` (voice-builder-pilot v2) — knows how to extract spec from utterance.
- `VoiceBuilderScreen` — established voice-first UX pattern.

Tauri:
- Tauri 2.x notification API (rust crate `tauri-plugin-notification`) — Windows Toast / macOS native.
- `tauri-plugin-global-shortcut` — already wired for hotkeys.

## v1 scope — 3 features (~5-7 days)

### F1: Voice Morning Briefing (~2 days)

**Goal:** every morning at user-configured time, KALI greets the user with a spoken summary of the day. No manual trigger.

**UX:**
- Default time: 8:00 AM (configurable in Settings → Voice).
- KALI is launched (assumed running in background — Tauri tray icon).
- At configured time, system speakers play: *"Доброе утро. Сегодня плюс три, две встречи в календаре в одиннадцать и в три. Water-tracker напомнит в десять и четырнадцать. Биткоин минус два процента за ночь."*
- If KALI not running at scheduled time, briefing fires on next launch (catch-up window: 4h).
- Setting toggle: on/off + time picker.

**Implementation:**
- New endpoint `POST /briefing/morning` (currently `/briefing/morning` exists for chat-side; extend to support cron-triggered + auto-TTS).
- New cron entry registered in `kernel/scheduler.py` driven by user setting `briefing_morning_time` (HH:MM, default `08:00`).
- Briefing assembly logic (existing in `_chat_logic`'s daily_briefing branch) refactored into `kernel/briefing/morning.py` for reuse.
- TTS auto-speak via `_speak_response` (already exists, `kernel/main.py:1052`).
- Settings UI: add Voice section in Settings page with time picker + toggle. Persist in `.env` as `KALI_BRIEFING_MORNING_TIME` and `KALI_BRIEFING_MORNING_ENABLED`.

**Out of scope for v1:** evening briefing, weekly recap, custom prompts (defer to v2).

### F2: OS Tray Notifications (~2 days)

**Goal:** notifier/monitor agents currently fire silently (only chat-side messages). Surface them via Windows Toast / macOS native — always visible, dismissible.

**UX:**
- Agent fires alert (e.g., notifier sees BTC -5%) → Windows Toast appears bottom-right with title (agent name) + body (alert text).
- Click toast → KALI window opens to chat with that agent's last message visible.
- Optional: TTS announce for important alerts (per-agent toggle, off by default; user enables for "biticoin notifier" but maybe not for "weather").
- Settings: per-agent on/off + global mute toggle.

**Implementation:**
- Tauri command `notify_agent` exposed via `tauri-plugin-notification`.
- Backend WebSocket event `agent:alert` published when notifier/monitor agent fires. Already broadcast in event bus (Phase 2).
- Frontend listens for `agent:alert` in `App.tsx` (or new `NotificationManager.tsx`), invokes Tauri notification command.
- Click handler routes to `mode === "agents"` and scrolls to the relevant agent's chat thread.
- Settings UI: per-agent toggle row in Agents tab.
- Persist: `.env` `KALI_NOTIFICATIONS_AGENT_<name>_ENABLED` and `KALI_NOTIFICATIONS_VOICE_<name>_ENABLED`.

**Out of scope for v1:** rich toast actions (action buttons in toast), notification grouping, snooze. (defer)

### F3: Suggestion Engine (~2-3 days)

**Goal:** detect repetitive user intent patterns and proactively suggest automation. Signature differentiator vs Orbit ("you don't ask, KALI suggests").

**UX:**
- Backend tracks chat intent classifications over a rolling 7-day window (local SQLite, never sent off-device).
- After 5+ messages classified to similar intent (e.g., user asks "курс биткоина" 5 times in a week), KALI surfaces a suggestion in chat:
  > *"Я заметил, ты часто спрашиваешь курс биткоина. Создать агента, который сам уведомит при изменении на 5 процентов?"*
- Suggestion has two buttons: **Создать** (opens `voice-builder-pilot` with pre-filled spec — template + extracted hints) and **Не сейчас** (snooze 7 days).
- Voice readback of suggestion if user has speakers on (re-uses TTS pipeline).
- Settings: global on/off toggle (default on).

**Implementation:**
- New table `chat_intent_log(id, timestamp, intent_class, classified_template, raw_text)` in existing SQLite (`kali.db`).
- Hook in `kernel/main.py` `/chat` handler — after intent classification (already happens via `intent_classifier`), append to log.
- Cron job (every 6h) scans last 7 days for intent clusters using existing `intent_classifier.classify_intent` rules + simple frequency count.
- When threshold (≥5 same intent) hit, suggestion record created in `suggestions` table (one per pattern, dedupe by intent_class+date).
- Frontend polls `GET /suggestions/active` on app focus, displays inline as system message in chat.
- "Создать" button calls existing `useBuilderStore.start(pre_filled_text)` to enter voice-builder-pilot flow with template hint pre-populated.
- "Не сейчас" → marks suggestion `snoozed_until: now + 7d` in DB.

**Privacy note:** intent log + raw_text never leaves device. Pattern data is local only. We DO NOT need to send to cloud — `intent_classifier` already runs locally for non-LLM rules, and even the LLM-fallback path uses already-configured user API key.

**Out of scope for v1:** suggestion engine learning user's actual preferences (just frequency counting), cross-device suggestion sync, suggestion analytics. (defer)

## Out of scope (parked for v2+)

- **Weekly Insights** — Sunday voice recap of the week ("за неделю ты создал 2 агента, наиболее активный water-tracker, биткоин рос 8%").
- **Multi-day trend analysis** — "ты в последние три недели всё чаще спрашиваешь про спорт".
- **Mobile push notifications** — Tier 4 mobile port territory.
- **Idle-time triggers** — "я заметил ты молчишь 4 часа, всё ок?".
- **LLM-driven proactive suggestions** — embedding-based pattern detection, requires embedding pipeline.
- **Cross-agent context awareness** — agents reading each other's outputs, parking until Tier 3 LLM router (Phase 6).

## Dependencies & gates

**Gates on:**
- Tier 2 #10 Agent Store v2 (catalog visibility — suggestion engine needs to know what templates exist for "Создать" button).
- Phase 2 WebSocket event bus (already shipped) — F2 needs.
- Premium TTS pipeline (already shipped post-Apr 29 fixes) — F1 needs.

**Does NOT gate on:**
- Rust Phase 5 (Builder in Rust) — voice-builder-pilot already in Python and works.
- Mobile Tier 4 — desktop-first, mobile gets these features when port lands.

## Success metrics

After v1 ships:
- ≥80% of returning users hear morning briefing within first week (proxy: `briefing_morning_played` events).
- ≥3 toast notifications fired per active user per week (proxy: notifier/monitor agents actually used).
- ≥1 user accepts a suggestion → creates an agent via `voice-builder-pilot` flow per week (UGC moment — "look, KALI offered to make me an agent, here's the reel").

## Implementation chunks (when execution plan written closer to start)

| Chunk | Tasks | Estimate |
|---|---|---|
| 1 | F1 backend (briefing/morning endpoint + cron + assembly refactor) | 1 day |
| 2 | F1 frontend (Settings UI for time + toggle, voice section) | 0.5 day |
| 3 | F2 backend (event bus alert publishing — confirm shape) + Tauri notification plugin wiring | 1 day |
| 4 | F2 frontend (NotificationManager listening to events + per-agent settings) | 1 day |
| 5 | F3 backend (intent log SQLite table + cron pattern detection + suggestions table + endpoints) | 1.5 days |
| 6 | F3 frontend (suggestion display + Create/Snooze buttons + integration with voice-builder-pilot) | 1 day |
| 7 | E2E vitest for full proactive flow + manual smoke test | 0.5 day |

Total: ~6.5 days. Buffer to 7 days for plan-defects in review-loop (precedent: 8 plan-defects caught during voice-builder-pilot v2 — same pattern expected).

## Reusing voice-builder-pilot review patterns

- Two-stage review (spec compliance → code quality) with fresh subagent per task.
- Plan-defects expected (8 caught last time across 25 tasks). Reviewer mistakes also expected (2 caught last time controller-rejected) — controller verifies reviewer claims.
- Lint-driven deviations OK (ruff E402 / F401 etc) — implementer flags in report; reviewer checks functional equivalence.
- Direct-to-main commits (no PR — solo dev convention).

## Open questions (resolve before plan written)

1. **Cron job persistence across reboots** — does `kernel/scheduler.py` survive process restart? If yes, briefing fires after reboot at next 8:00. If no, need OS-level scheduler integration. (Investigate during chunk 1.)
2. **Notification permission on Windows** — does Tauri auto-request on first send, or need explicit prompt during onboarding? (Investigate during chunk 3.)
3. **Suggestion language** — generation of "Я заметил ты часто X" string — template-based or LLM-rendered? Template avoids cloud dep but feels canned. LLM (using user's existing API key) makes it natural but adds latency. (Recommendation: template for v1, LLM for v2.)

## Migration notes

No breaking changes. New endpoints, new SQLite tables, new settings keys. Existing flows untouched.

`config/kali.yaml` gains optional `briefing.morning_time` and `briefing.morning_enabled` fields with defaults.

---

*Spec to be reviewed before plan written. Estimated plan-write effort: 1 day. Plan execution: 5-7 days per chunks above.*
