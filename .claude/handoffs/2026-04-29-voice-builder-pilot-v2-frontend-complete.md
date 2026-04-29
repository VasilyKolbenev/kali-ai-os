---
handoff_date: 2026-04-29
project: KALI — voice-builder-pilot v2 implementation
branch: main
latest_commit: 7737b77
plan: docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md
spec: docs/superpowers/specs/2026-04-28-voice-builder-pilot-design.md
chunks_done: 8 of 8 (frontend complete; manual rehearsal pending)
tasks_done: 24 of 25 (Task 25 blocked on user mic)
session_commits: 21 (12 feat + 9 fix)
supersedes: 2026-04-28-voice-builder-pilot-chunks-1-3.md
---

# voice-builder-pilot v2 — Frontend Complete, Manual Rehearsal Pending

24 of 25 tasks shipped. The voice-first builder UI is fully integrated, type-safe, and unit-tested. Only Task 25 (the live mic rehearsal) remains — gated on Vasily having the dev shell running with a working microphone.

## What this session delivered

**Chunk 4 — Frontend foundation (Tasks 10-11, 3 commits):**
- `9975b31` Task 11: `builderApi` adds `extract`, `transcribe`, `say` (shipped first via swap-reorder so Task 10 lands tsc-clean)
- `b22cbe6` Task 10: `useBuilderStore` 9-phase voice state machine + `editField` + `previewSubState` + `questions[]`
- `d419edd` Task 10 race fix: `_submitGen` guard kills stale STT/extract promises after `cancel()` + 5th vitest exercising the race

**Chunk 5 — Audio + Orb (Tasks 12-14, 6 commits):**
- `b7e9596` Task 12: `useAudioCapture` (MediaRecorder blob path + AnalyserNode polled live frames + Float32→Int16)
- `6bdb5d6` Task 12 critical fix: `InvalidStateError` guard on `recorder.stop()` + partial-init cleanup if `MediaRecorder` constructor throws (Safari/iOS) + `decodeCtx.close()` view-invalidation copy + per-tick `Float32Array(buf)` immutability fix
- `c617c44` Task 13: `useRmsVad` (1.5s silence detection, `Date.now`-driven)
- `7ec283d` Task 13 fix: corrected misleading "200 frames" comment + replaced magic 31 with `Math.floor(silenceMs / CHUNK_MS) + 1` derivation
- `02d3561` Task 14: `VoiceOrb` (idle/listening/processing tri-state)
- `e585c8c` Task 14 fix: `pulse` keyframe was missing, renamed reference to existing `@keyframes pulse-orb`

**Chunk 6 + Chunk 7 (Tasks 15-21, swap-reordered, 9 commits):**
- `b737a01` Task 15: `LiveTranscript` leaf component
- `4820f64` Task 16: `SpecCard` (filled/muted/highlighted) — added description row to satisfy plan-spec test (`description: "трекер"` had no rendering target in plan-literal JSX)
- `067fb0f` Task 17: `WizardPrompt` with TTS readback on mount
- `8bca591` Task 19: `voiceCommands` parser with disambiguation rule (whole-token edge-match for cancel; ≤3-token cancel rule for asking; FIELD_KEYWORDS substring for edit)
- `e759fc1` Task 19 fix: `_tokens` regex now strips em-dash, en-dash, ellipsis, soft hyphen — faster-whisper emits these in Russian transcripts
- `9a24bf8` Task 20: `PreviewConfirm` — A6 readback + deploy/cancel buttons. Test mock had to add `setPreviewSubState: vi.fn()` (plan-spec mock omission).
- `6d9e3d2` Task 18: `VoiceBuilderScreen` replaces `BuilderPanel` + 3 sub-components. App.tsx swap. `Builder/` folder kept (orphan `Builder.tsx` preserved per controller decision).
- `03eb63e` Task 18 critical fix: ref-tracked `audio.isRecording` for unmount cleanup (was reading stale closure → mic LED stays lit after mode switch). Replaced `var(--j-error, #f87171)` with `var(--j-danger)` (token consistency). Removed dead ESLint suppression (no ESLint installed in this project).
- `44fb547` Task 21: cross-turn audio re-start `useEffect` when entering `listening_for_answer` / `listening_for_command` sub-states.

**Chunk 8 — Polish (Tasks 22-24, 3 commits; Task 25 pending):**
- `ce629b5` Task 22: first-mount mic-permission intro banner (localStorage flag `kali.voice_builder.intro_seen`)
- `7cb9cf2` Task 23: visible error recovery affordances (Сбросить + Печатать вместо buttons inside the error block)
- `7737b77` Task 24: e2e vitest for `VoiceBuilderScreen` (ESC cancel + text-fallback paths). Mocks audio capture and builderApi at the module boundary.

**Reorder rationale (Tasks 18 ↔ 19/20):** Task 18 imports `parseVoiceCommand` (Task 19) and `PreviewConfirm` (Task 20). Plan-literal had Task 18 in Chunk 6 and Tasks 19+20 in Chunk 7, requiring a stub for `PreviewConfirm` (plan addressed) AND another for `voiceCommands` (plan forgot). Same pattern as the Task 11 ↔ Task 10 swap from Chunk 4 — controller-approved by user. Result: Task 18 ships with no stubs and zero forward-ref tsc breaks.

**Test totals (all green):**
- Frontend: **98 passed / 1 skipped** across 32 files (was 63/1 / 22 files at the prior handoff). Delta +35 across the 21 frontend commits.
- Backend: untouched this session, still 95 passed in ~15s (Chunks 1-3 baseline).
- tsc: clean across all UI commits (manual verification at every commit).

## Plan-defects caught by review-loop this session

The two-stage review (spec compliance → code quality) caught **eight real defects** in 14 implementation commits — same dispatch-cost-justifying ratio as the backend session.

1. **Task 10 — Race in `submitAudio`/`start`:** stale STT/extract promise resolves after `cancel()` and overwrites the reset store. Fixed with a `_submitGen` counter, guards after every `await`, and a 5th vitest that exercises the race with a controllable Promise. (`d419edd`)
2. **Task 12 — `recorder.stop()` on inactive `MediaRecorder` → `InvalidStateError`:** realistic in the VAD-auto-stop + manual-tap collision path. Fixed with state guard. (`6bdb5d6`)
3. **Task 12 — `start()` partial-init leaks resources if `MediaRecorder` constructor throws:** Safari/iOS scenario (`audio/webm;codecs=opus` unsupported). Fixed with try/catch cleanup wrapper. (`6bdb5d6`)
4. **Task 12 — Shared mutable `buf` passed to `onFrame`:** if `useRmsVad` ever stored the frame across ticks it would corrupt. Fixed with per-tick `new Float32Array(buf)` copy. (`6bdb5d6`)
5. **Task 13 — Plan-spec test math:** plan said 25 iterations after a loud-frame reset, but math required ≥31 to fire `onSilence`. Implementer caught and fixed; test now uses `Math.floor(1500 / CHUNK_MS) + 1` for self-documentation. (`c617c44` + `7ec283d`)
6. **Task 14 — `@keyframes pulse` referenced but doesn't exist:** controller pre-flight grep was substring-fooled by `pulse-ring`/`pulse-orb`. Listening orb silently didn't pulse. Fixed by renaming the animation reference to existing `pulse-orb`. (`e585c8c`)
7. **Task 19 — `_tokens` regex missing Unicode dashes/ellipsis:** faster-whisper emits `—`, `–`, `…` in Russian transcripts. `"стоп—продолжай"` would tokenize as a single token, breaking cancel detection. Fixed regex to strip these. (`e759fc1`)
8. **Task 18 — Stale `audio.isRecording` in unmount cleanup:** `useAudioCapture` returns a new object literal every render, but the `useEffect([])` cleanup captures the mount-time object. User switches mode mid-recording → cleanup reads stale `false` → `audio.stop()` not called → OS mic LED stays lit. Fixed with ref-tracked `isRecording`. (`03eb63e`)

**Plus one controller-rejected reviewer mistake:** Task 16 reviewer flagged "Important — missing `?? "-"` fallbacks for `name` and `description`". Per `BuilderPreview` type contract, those fields are `string` (always present); only `template: string | null` warrants the fallback. Plan-literal stands. Documented as a non-issue.

**Plan-defect categories:**
- **Race conditions** (Task 10, Task 12 stop): cleanup didn't account for in-flight promises / event listeners.
- **Browser API edge cases** (Task 12 start): Safari MIME-type rejection, AudioContext invalidation.
- **Test fixture drift** (Task 13, Task 16, Task 20): plan-spec tests expected behavior the JSX/mock didn't actually expose.
- **Real-world data drift** (Task 19): STT output has Unicode beyond the ASCII punctuation covered.
- **Stale closures from object identity** (Task 18 isRecording): React refs returning new objects every render are easy to over-trust.

The pattern holds: even after 4 plan-review iterations, code-quality reviewers find issues the planner missed. Reviewer dispatch cost is well-justified.

## What's left — Task 25 (manual rehearsal)

**Blocking on:** Vasily's dev machine with working microphone access. The 5 voice runs cannot be automated.

### Rehearsal protocol

```bash
# Shell A — Python backend (FastAPI)
.venv/Scripts/python.exe -m kernel.main

# Shell B — frontend build + Tauri shell
pnpm --dir ui build && cargo run --manifest-path src-tauri/Cargo.toml
```

(Use `pnpm`, not `npm` — the project has `ui/pnpm-lock.yaml`.)

In the Tauri devtools console, **before each rehearsal** clear the first-mount banner so the cold-start UX is exercised:
```js
localStorage.removeItem("kali.voice_builder.intro_seen")
```

Then voice-say each prompt and record what the extractor produced. Target **≥4/5 success** ("success" = correct template + dominant config field correctly populated + agent deploys without backend error).

| # | Prompt (voice) | Expected template | Expected config keys filled | Result |
|---|----------------|-------------------|----------------------------|--------|
| 1 | трекер воды два литра каждые два часа в чат | `tracker` | interval=2 часа, goal=2 литра, notify_channel=чат | TBD |
| 2 | напоминай делать растяжку каждый час | `reminder` | interval=каждый час | TBD |
| 3 | проверяй курс биткоина каждые пять минут и уведомляй в телеграм если упал на пять процентов | `notifier` | trigger=*5%* / *упал*, notify_channel=телеграм | TBD |
| 4 | веди дневник настроения раз в день голосом | `logger` | categories=настроение | TBD |
| 5 | следи за сайтом example.com каждые десять минут и уведомляй если недоступен | `monitor` | target=example.com, interval=10 минут | TBD |

### Symptom → likely fix table

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| STT mishears (~40% word loss) | `useRmsVad` threshold too eager / cut-off too early | bump `silenceMs` from 1500 to 2000ms; tune RMS threshold |
| TTS readback feels slow / clipped | Cold-load on first call | check kernel log for "TTS prewarm: ready" — should print at startup (Task 9 fix) |
| Wrong template selected | Extractor LLM prompt missing example | add a worked example for the failing pattern to `LLM_SYSTEM_PROMPT` in `kernel/builder/extractor.py` |
| Deploy fails with name collision | Existing skill with same slug | retry with a different name in the prompt; or `rm -rf agents/<slug>` first |
| Silent banner stays / banner never dismisses | localStorage write failing | check Tauri's localStorage backing; the dismiss button has try/catch but won't surface failures |

If a symptom isn't covered here, surface to Vasily before guessing — spec line 537 promises "zero broken states" with documented recovery for everything.

## Carry-forwards (deferred, NOT blockers for rehearsal)

These were explicitly deferred during the session. None affect the rehearsal:

- **Task 14 color drift:** `rgba(0,224,255,...)` inline in `VoiceOrb.tsx` doesn't match `--j-cyan = #00d4ff`. Visual nit; replace with `var(--j-cyan-glow)` / `var(--j-cyan-soft)` during a Chunk 6 visual QA pass. Reviewer-flagged, plan-literal preserved.
- **Task 14 processing visually = idle:** `background` and `boxShadow` only differ on `listening`; `processing` only swaps the icon. User may not notice the spinner on a 96px button. Worth distinct background tier.
- **Task 17 `WizardPrompt` JSDoc:** could document the `onTtsDone` stability requirement so future consumers know to wrap in `useCallback`. Carry-forward addressed by Task 18's wrap; not blocking.
- **Task 19 `_tokens` test coverage:** untested edge cases (empty string, "поправь" with no field, edit on unknown field). All return `unknown` correctly; deferred to manual rehearsal validation.
- **Task 24 e2e wider coverage:** plan title said "golden + wizard fallback + cancel" but only 2 cases shipped (cancel + text-fallback). Wizard-fallback (extract → complete: false → asking → answer flow) is exercised by manual rehearsal #1.
- **Out-of-scope spawned task:** `/tts/speak` returns errors with HTTP 200 + `{"error": ...}` body — backend bug flagged via `mcp__ccd_session__spawn_task` during Task 11 code-quality review. Will surface as silent TTS failure if F5/ElevenLabs is broken; will manifest as silence (not error UX) during the rehearsal. Fix-up tracked separately.

## Files touched this session (21 commits)

| File | Net lines | Tasks |
|------|-----------|-------|
| `ui/src/api/builder.ts` | +42 / -9 | 11 |
| `ui/src/stores/builder.ts` | ~+205 (rewrite) | 10 (+ race fix) |
| `ui/src/stores/__tests__/builder.test.ts` | +145 (new + race test) | 10 |
| `ui/src/components/VoiceBuilder/useAudioCapture.ts` | +156 (new + leak fix) | 12 |
| `ui/src/components/VoiceBuilder/__tests__/useAudioCapture.test.ts` | +120 (new) | 12 |
| `ui/src/components/VoiceBuilder/useRmsVad.ts` | +62 (new) | 13 |
| `ui/src/components/VoiceBuilder/__tests__/useRmsVad.test.ts` | +75 (new + comment fix) | 13 |
| `ui/src/components/VoiceBuilder/VoiceOrb.tsx` | +50 (new + keyframe fix) | 14 |
| `ui/src/components/VoiceBuilder/__tests__/VoiceOrb.test.tsx` | +35 (new) | 14 |
| `ui/src/components/VoiceBuilder/LiveTranscript.tsx` | +22 (new) | 15 |
| `ui/src/components/VoiceBuilder/__tests__/LiveTranscript.test.tsx` | +17 (new) | 15 |
| `ui/src/components/VoiceBuilder/SpecCard.tsx` | +61 (new + description row) | 16 |
| `ui/src/components/VoiceBuilder/__tests__/SpecCard.test.tsx` | +45 (new) | 16 |
| `ui/src/components/VoiceBuilder/WizardPrompt.tsx` | +30 (new) | 17 |
| `ui/src/components/VoiceBuilder/__tests__/WizardPrompt.test.tsx` | +25 (new) | 17 |
| `ui/src/components/VoiceBuilder/voiceCommands.ts` | +77 (new + Unicode regex fix) | 19 |
| `ui/src/components/VoiceBuilder/__tests__/voiceCommands.test.ts` | +50 (new) | 19 |
| `ui/src/components/VoiceBuilder/PreviewConfirm.tsx` | +63 (new) | 20 |
| `ui/src/components/VoiceBuilder/__tests__/PreviewConfirm.test.tsx` | +52 (new + mock fix) | 20 |
| `ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx` | +260 (new + isRecording ref + token fix + intro banner + error UX) | 18, 21, 22, 23 |
| `ui/src/components/VoiceBuilder/__tests__/VoiceBuilderScreen.test.tsx` | +62 (new) | 24 |
| `ui/src/components/VoiceBuilder/StarterExamples.tsx` | (renamed from `Builder/`) | 18 |
| `ui/src/App.tsx` | +1 / -1 (import + JSX swap) | 18 |
| `ui/src/components/Builder/{BuilderPanel,BuilderProgress,BuilderPreview}.tsx` | (deleted) | 18 |

Plus `ui/src/components/Builder/Builder.tsx` — preserved as legacy orphan per controller decision.

## Build / test commands (carry-forward)

```bash
# Backend tests (still 95/1 from Chunks 1-3)
.venv/Scripts/python.exe -m pytest tests/kernel/builder/ \
  tests/kernel/test_builder_endpoints.py \
  tests/kernel/voice/ \
  tests/kernel/test_voice_transcribe_endpoint.py \
  tests/kernel/test_main.py -v

# Frontend tests (98/1 across 32 files)
cd ui && pnpm test && npx tsc --noEmit

# Lint
uvx ruff check kernel/ tests/
```

## Continuation pattern

If Vasily wants to do the rehearsal in a fresh session:

1. **Resume in a fresh session.**
2. **Skill stack:** `superpowers:using-superpowers`. (No subagents needed — Task 25 is manual.)
3. **Read order:**
   - This handoff
   - The "Manual rehearsal protocol" section above
   - Recent commits (`git log --oneline -22`)
4. **Verify pre-flight:**
   ```bash
   .venv/Scripts/python.exe -m pytest tests/kernel/ -q
   cd ui && pnpm test && npx tsc --noEmit
   ```
   Expect: backend ~95/1 in 15s, frontend 98/1 in ~10s, tsc clean.
5. **Run the 5 rehearsals.** Fill in the result column above. If all 5 pass, voice-builder-pilot v2 is fully shipped — write a final commit `docs(handoff): voice-builder-pilot v2 SHIPPED + rehearsal results` and update memory `MEMORY.md` head pointer to a v2.13 SHIPPED snapshot.

## Side-effects worth noting

- All 21 commits land directly on `main` per Vasily's solo-dev convention.
- Two reviewer dispatches for Tasks 16 and 17 raised issues the controller pushed back on (Task 16 non-nullable string fallbacks; Task 17 inline lambda was actually fixed in Task 18 via `useCallback`, not in Task 17 itself). These are documented as patterns: reviewers can be wrong, and the controller's job is technical rigor, not performative agreement.
- The `ui/src/components/Builder/Builder.tsx` orphan (separate from `BuilderPanel`) is preserved untouched. Not imported from `App.tsx` or anywhere else; using `api.builderClassify` (different code path). Safe to delete in a future cleanup, but not in this PR.
- Spec commit `46561be` (the design spec) is older than the rolling 21-commit window in this handoff — predates Chunk 1. It's still the source of truth for design rationale.

---

*Handoff created 2026-04-29 after 24 of 25 voice-builder-pilot tasks shipped (Chunks 1-8 complete code-wise; Task 25 manual rehearsal pending). Backend, all UI, e2e tests in. 21 frontend commits this session, 8 plan-defects caught by review-loop. Next session: 5 voice rehearsals + final SHIPPED commit.*
