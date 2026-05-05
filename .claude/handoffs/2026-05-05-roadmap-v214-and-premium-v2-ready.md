---
handoff_date: 2026-05-05
project: KALI — Premium v2 install + dual rehearsal + Tier 2 next steps
branch: main
latest_commit: 9276e9f
roadmap_revision: v2.14
plan_active: docs/superpowers/specs/2026-05-05-proactive-kali-v1.md (next plan to write)
prior_handoff: 2026-04-29-voice-builder-pilot-v2-frontend-complete.md
session_commits_since_prior_handoff: 3 (510b5d6 Premium fixes, 90bf7ef AgentCard toast, 9276e9f Proactive KALI v1 spec)
status_summary: Premium v2 installer ready Apr 29 22:29; awaiting reinstall + Gate A + Gate B; roadmap updated v2.14 (Orbit positioning, Mobile Tier 4)
---

# KALI Status — 2026-05-05

After 6-day pause (Apr 29 → May 5), session focused on (a) infrastructure fixes for Premium installer reported broken during user's Apr 29 testing, (b) roadmap update v2.14 incorporating Anthropic Orbit positioning + mobile architecture clarity from Edge AI vacancy review.

## What this session delivered

### Code (3 commits since last handoff)

| SHA | What |
|---|---|
| `510b5d6` | fix(premium): bundle openwakeword/F5/vocos data + persist onboarding_completed |
| `90bf7ef` | feat(ui): AgentCard surfaces toast feedback on START/STOP |
| `9276e9f` | docs(spec): proactive-kali-v1 — voice briefing + tray notifications + suggestion engine |

### Premium v2 build artifacts (ready, NOT installed by user yet)

```
dist_premium/installer/
├── KALI-Premium-Setup-0.2.0-beta.exe    3.1 MB  (wizard stub, Apr 29 22:29)
├── KALI-Premium-Setup-0.2.0-beta-1.bin  2.0 GB  (Apr 29 22:20)
└── KALI-Premium-Setup-0.2.0-beta-2.bin  1.7 GB  (Apr 29 22:29)
                                  total: ~3.7 GB
```

What changed in v2 vs v1 (which user tested Apr 29):
- `--collect-data openwakeword` → `hey_jarvis_v0.1.onnx` + base preprocessor + melspectrogram bundled. **Wake-word "Джарвис, привет" expected to work.**
- `--collect-data f5_tts vocos ruaccent faster_whisper` → F5-TTS engine bundled. **Chat TTS auto-speak expected to work** (300MB HF download on first call).
- `kernel/main.py` `/settings` GET+POST accept `onboarding_completed` field, persist to `.env` as `KALI_ONBOARDING_COMPLETED`. **Onboarding will not show again after first completion.**
- `AgentCard` inline toast feedback on START/STOP (button disable during loading + 4s success message + hint). **Agents tab now gives feedback.**

### Roadmap v2.14 (memory/project_roadmap.md)

**Anthropic Orbit positioning response.** Orbit launches ~May 6 (SF Code with Claude conf) — proactive AI for Claude Cowork integrating Gmail/Slack/GitHub/Calendar/Drive/Figma. Same proactive-AI thesis but tech-audience + cloud + Max-tier paid ($200/mo).

**KALI's response (binding):**
1. **Anti-pivot rule:** No dev/design integrations (GitHub/Figma/IDE). Orbit territory — KALI loses there.
2. **New Tier 2 #10.5 — Proactive KALI v1** (5-7d): voice morning briefing + OS tray notifications + suggestion engine. Spec: `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md`. Direct counter to Orbit's text dashboards.
3. **Mobile graduated** from "parked" to **Tier 4 — Mobile + UGC mass scale** (post-Tier 3, ~6-8w): 90/10 edge-cloud hybrid. Edge for STT/wake/skill execution/native TTS; cloud for agent creation (Claude/GPT-4o quality required for extractor + skill_generator).

### Memory updates

- `memory/MEMORY.md` head pointer → v2.14
- `memory/project_roadmap.md` v2.14 entry + Tier 2 #10.5 row + Tier 4 section
- `memory/project_competition.md` Competitor 3 — Orbit added with escalation triggers
- `memory/feedback_mobile_edge_ai_2026.md` — 90/10 hybrid strategy + edge/cloud split + anti-pivot + when-to-revisit triggers

## Two pending gates blocking Tier 2 #10

| Gate | What | Why blocking |
|---|---|---|
| **A** (Phase 3 cutover) | Live voice rehearsal Rust pipeline (wake → STT → /chat → TTS → playback) + flip `voice.engine: rust` in `config/kali.yaml` + commit | Tier 1 not fully closed until cutover commits |
| **B** (voice-builder-pilot Task 25) | 5 voice prompts in voice-builder-pilot mode → ≥4/5 success on template extraction + agent deploy | Voice-builder-pilot v2 stays 24/25 until rehearsal done |

Both require: **Premium v2 installed** (currently on disk: v1, Apr 29 18:56) + working mic + new backend running.

## Test status (verified May 5)

```
Backend fast suite: 95 passed in 15s ✅
Frontend tests:     98 passed | 1 skipped (32 files) ✅
TypeScript:         tsc --noEmit exit 0 ✅
```

Full backend pytest has 20 pre-existing failures (chip already spawned: lazy-import mock mismatch in `agent_generator.py`, NOT regression).

## Tomorrow's plan

### Phase 1 — Recovery (1-2 hours)

```
1. SHUTDOWN /R /T 0   # reboot — kills zombie kali-backend.exe (PID 18820 still
                     # showed C:\Program Files\KALI path on May 5 — old install
                     # uninstalled by user but process never killed properly)
2. After reboot — DO NOT launch KALI from anywhere
3. Run: dist_premium/installer/KALI-Premium-Setup-0.2.0-beta.exe
4. Inno Setup auto-overwrites existing 0.2.0-beta install in
   %LOCALAPPDATA%\Programs\KALI\
5. Smoke test ALL fixes:
   • Onboarding → "Джарвис, привет" должен реагировать
   • Pass onboarding once → restart KALI → onboarding NOT shown
   • Chat: ask "Как дела?" → response + TTS озвучивает
   • Agents tab → click START on calendar → toast "✓ calendar запущен. Напишите: 'события сегодня'"
   • Skills tab → click Refresh ↻ on Anthropic Official → cards appear → click Install on one → success
```

### Phase 2 — Close two gates (1-2 hours)

```
6. Gate A:
   • Verify Rust :3006 alive (curl http://localhost:3006/health → 200)
   • Edit config/kali.yaml — flip voice.engine to rust
   • Restart KALI
   • Live rehearsal: "Джарвис, привет" → "Какая погода?" → response in voice
   • If green → commit:
     git add config/kali.yaml
     git commit -m "feat(voice): cutover engine=rust default after live rehearsal"
   → Tier 1 FULLY closed.

7. Gate B (voice-builder-pilot Task 25):
   • Open KALI → mode "Создать агента" (or Sidebar → builder)
   • Voice 5 prompts from handoff Apr 29 manual rehearsal table:
     1. трекер воды два литра каждые два часа в чат → tracker
     2. напоминай делать растяжку каждый час → reminder
     3. проверяй курс биткоина каждые пять минут и уведомляй в телеграм если упал на пять процентов → notifier
     4. веди дневник настроения раз в день голосом → logger
     5. следи за сайтом example.com каждые десять минут и уведомляй если недоступен → monitor
   • Gate: ≥4/5 success (correct template + dominant config field + clean deploy)
   • Update memory v2.15 with results
   • Optionally: write final voice-builder-pilot SHIPPED handoff
   → voice-builder-pilot v2 = 25/25 SHIPPED.
```

### Phase 3 — Plan next sprint (1-2 hours)

```
8. Brainstorm one of (or recommend Vasily picks order):
   • Tier 2 #10 Agent Store v2 spec (~7-10d implementation) — App Store + TikTok feel
   • Tier 2 #10.5 Proactive KALI v1 plan (~5-7d implementation) — fast wow before
     friend distribution. Spec already written 9276e9f. Just needs execution plan.

   Recommendation: invert order — do #10.5 BEFORE #10. Reasoning:
   • Faster wow factor (5-7d vs 7-10d).
   • Direct Anthropic Orbit counter — voice ambient differentiates immediately.
   • Friend distribution with proactive features = stronger UGC moments.
   • #10 Agent Store can wait — current Skills catalog functional after Premium v2 install.

9. After plan written → execute via subagent-driven-development pattern
   (precedent: voice-builder-pilot v2 — 21 commits, 8 plan-defects caught,
   2 reviewer mistakes controller-rejected).
```

## Carry-forward decisions and rules

### Binding rules from prior sessions
- **Direct-to-main commits** — solo dev, no PR review.
- **Documentation commits OK** without explicit go (specs, plans, memory).
- **Feature/refactor commits** wait for "ок" / "го" / "давай" / "поехали".
- **Plan-defects expected** — voice-builder-pilot v2 caught 8 across 25 tasks via review-loop. Two-stage review (spec → code-quality) non-negotiable.
- **Reviewer can be wrong** — controller verifies reviewer's reasoning by reading actual code, not trust.
- **`.venv/Scripts/python.exe -m pytest`** for stable runs; NOT `uv run pytest`.
- **`KALI_SKIP_PREWARM=1`** stays in `tests/conftest.py` — without it test suite adds 6 minutes ML cold-load.
- **Russian-first communication** — ответы на русском, код и tech terms на английском.
- **"Предложи → обсудим → сделаем"** — non-trivial work requires explicit go.

### Roadmap binding rules added 2026-05-05
- **Anti-pivot:** NO dev/design integrations (GitHub/Figma/IDE). Doubling down on voice + non-tech.
- **Mobile = "remote + run", NOT "build"** — agent creation stays cloud-routed (Claude/GPT-4o quality required).
- **Mobile work doesn't start until Tier 3 closes** (Phase 8 Python retire complete).

## Open spawned-task chips (don't lose)

1. **Backend `/tts/speak` HTTP-200-on-error** — flagged during Task 11 voice-builder-pilot review. `kernel/main.py:1432, 1446` returns `{"error": ...}` with 200 instead of HTTPException. Frontend `postJson` reads only `if (!r.ok)`. Could surface as silent TTS failure.
2. **20 pre-existing pytest failures** — `agent_generator.py` lazy-import vs test mocks. Test debt, NOT a regression. Fix: update tests to use `patch.dict("sys.modules", ...)` or `patch("anthropic.Anthropic")`. DO NOT add top-level import (would couple to optional dep).

## Files touched this session (May 5)

| File | Change |
|---|---|
| `scripts/build_backend_premium.py` | +12 lines — COLLECT_DATA list for openwakeword/f5_tts/vocos/ruaccent/faster_whisper |
| `kernel/main.py` | +5 lines — `onboarding_completed` GET+POST + .env persistence |
| `ui/src/components/AgentPanel/AgentCard.tsx` | +35 / -27 — toast feedback (success/error/loading) |
| `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md` | NEW 173 lines |
| `memory/MEMORY.md` | head pointer v2.14 |
| `memory/project_roadmap.md` | v2.14 entry + Tier 2 #10.5 + Tier 4 section + risks |
| `memory/project_competition.md` | Competitor 3 — Orbit |
| `memory/feedback_mobile_edge_ai_2026.md` | NEW — full mobile strategy |
| `.claude/handoffs/2026-05-05-roadmap-v214-and-premium-v2-ready.md` | THIS file |

## Continuation pattern for the next session

1. **Resume in fresh session** when Vasily ready (likely tomorrow May 6).
2. **Skill stack:** `superpowers:using-superpowers` (auto) → execution skill TBD based on chosen path.
3. **Read order:**
   - This handoff (`.claude/handoffs/2026-05-05-roadmap-v214-and-premium-v2-ready.md`)
   - `memory/project_roadmap.md` v2.14 entry
   - `memory/project_competition.md` (Orbit)
   - `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md` (proactive spec)
   - `memory/feedback_mobile_edge_ai_2026.md` (mobile context)
4. **Verify state:**
   ```bash
   git log --oneline -5
   # top must be 9276e9f (proactive-kali-v1 spec)

   .venv/Scripts/python.exe -m pytest tests/kernel/builder/ \
     tests/kernel/test_builder_endpoints.py \
     tests/kernel/voice/ \
     tests/kernel/test_voice_transcribe_endpoint.py \
     tests/kernel/test_main.py -q
   # Expected: 95 passed in ~15s

   cd ui && pnpm test && npx tsc --noEmit
   # Expected: 98 passed | 1 skipped, tsc 0
   ```
5. **Confirm Premium v2 install state** — ask Vasily directly: "did the v2 install go OK? Smoke test results?"
6. **Branch decision:**
   - All 5 smoke tests pass → proceed to Gate A + Gate B → then plan #10.5 or #10.
   - Some smoke tests fail → diagnose root cause → patch → rebuild → re-deploy.

---

*Handoff created 2026-05-05. State of art: Premium v2 ready, roadmap v2.14 anchored, Tier 2 #10.5 spec written, mobile architecture clarified Tier 4. Next: dual rehearsal then sprint #10.5 (recommended) or #10.*
