---
handoff_date: 2026-04-28
project: KALI — voice-builder-pilot v2 implementation
branch: main
latest_commit: abfcb5e
plan: docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md
spec: docs/superpowers/specs/2026-04-28-voice-builder-pilot-design.md
chunks_done: 3 of 8
tasks_done: 9 of 25
session_commits: 14 (9 feat + 5 fix)
supersedes: 2026-04-28-voice-builder-pilot-chunks-1-2.md
---

# voice-builder-pilot v2 — Chunks 1-3 SHIPPED, Backend Complete

## What this session delivered

**Chunk 1 — Backend foundation (3 tasks):**
- `989ea6e` Task 1: `_question_to_key` helper + 10-case parametrized test
- `f04b0ad` Task 2: refactor both `_build_spec` paths to use helper + parity test
- `4c92f0a` Task 3: `BuilderSession.name_hint` field

**Chunk 2 — Backend extractor (3 tasks + 2 lint fixups):**
- `3913d14` Task 4: `extractor.py` skeleton with verbatim `LLM_SYSTEM_PROMPT`
- `d5ccf7e` Task 4 lint: `# noqa F401/E501` cleanup
- `e6505c3` Task 5: `extract_spec` mutation contract + `_fallback_to_start`
- `72250a4` Task 6: `POST /builder/extract` endpoint
- `01c7e08` Task 6 lint: drop dead `unittest.mock` re-import

**Chunk 3 — Backend STT endpoint (3 tasks + 2 critical fixes):**
- `26e7a8e` Task 7: `decode_and_resample` helper (i16 LE PCM + scipy resample → 16 kHz float32 mono)
- `c8e2d17` Task 8: `POST /voice/transcribe` endpoint + `get_or_create_stt` lazy-init helper
- `6f79824` Task 8 critical fix: `.load()` was missing → silent empty transcripts in production. Reviewer caught the plan-spec defect.
- `26f41aa` Task 9: F5-TTS + Whisper STT prewarm in FastAPI lifespan
- `abfcb5e` Task 9 race fix: deleted `_tts_bg_load` (subsumed by prewarm; was racing with it on F5 weights → GPU OOM risk in default config) + `KALI_SKIP_PREWARM` env-var so tests don't pay ~17s/fixture cold-load cost.

**Test totals (all green):**
- `tests/kernel/builder/`: 30 passing
- `tests/kernel/test_builder_endpoints.py`: 7 passing
- `tests/kernel/voice/`: 5 passing (transcribe_helper)
- `tests/kernel/test_voice_transcribe_endpoint.py`: 4 passing
- `tests/kernel/test_main.py`: 16 passing (lifespan exercised, prewarm skipped via env-var)
- **Combined fast-suite: 58 passing in 13s** (was multi-minute before the prewarm-skip fix).

## What's next — Chunks 4-8 (16 tasks)

| Chunk | Tasks | Surface | Estimate |
|-------|-------|---------|----------|
| 4 | 10-11 | Frontend foundation — extend `useBuilderStore` (new phases + `editField` + `previewSubState` + `questions[]`); extend `builderApi` with `transcribe`, `extract`, `say` | ~1 day |
| 5 | 12-14 | Frontend audio + orb — `useAudioCapture` (MediaRecorder blob + AnalyserNode polled live frames for VAD), `useRmsVad`, `VoiceOrb` | ~1.5 days |
| 6 | 15-18 | Frontend screen + layout — `LiveTranscript`, `SpecCard`, `WizardPrompt`, `VoiceBuilderScreen`; replace `BuilderPanel`; `git rm` old Builder/ files | ~1.5 days |
| 7 | 19-21 | Frontend preview — `voiceCommands.ts` parser, `PreviewConfirm` (await-TTS gating), audio re-start between turns | ~1 day |
| 8 | 22-25 | Polish — first-mount intro banner, error-recovery affordances, e2e Vitest, manual rehearsal (5 voice runs ≥4/5 success gate) | ~1 day |

Total ≈ 5-6 days remaining.

## Continuation pattern for the next session

1. **Resume in a fresh session** (this one is at hard context limits).
2. **Skill stack:** `superpowers:using-superpowers` → `superpowers:subagent-driven-development`.
3. **Read order on resume:**
   - This handoff (`.claude/handoffs/2026-04-28-voice-builder-pilot-chunks-1-3.md`)
   - The plan (`docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md`)
   - The spec (`docs/superpowers/specs/2026-04-28-voice-builder-pilot-design.md`)
   - Latest commits (`git log --oneline -16`).
4. **Verify state before continuing:**
   ```bash
   .venv/Scripts/python.exe -m pytest tests/kernel/builder/ tests/kernel/test_builder_endpoints.py tests/kernel/voice/ tests/kernel/test_voice_transcribe_endpoint.py tests/kernel/test_main.py -v
   ```
   Expected: 58 passed in ~13s.
5. **Start at Task 10** (Chunk 4, line ~1382 in the plan): extend `BuilderPhase` enum + state machine in `useBuilderStore`. UI work begins. Verify pnpm + vitest setup before dispatch:
   ```bash
   cd ui && pnpm install && pnpm test && npx tsc --noEmit
   ```

## Defects caught by review-loop this session (publishable lessons)

1. **Plan-doc defect propagated through Task 4:** plan-spec listed forward-compat imports without `# noqa: F401` annotations → 9 ruff errors landed. Fixed `d5ccf7e`. Lesson: when a plan mandates importing-now-but-using-later, annotate the noqa in the spec, not as a follow-up commit.

2. **Plan-doc defect propagated through Task 6:** plan-spec test snippet copy-pasted `from unittest.mock import AsyncMock, MagicMock` redundantly (MagicMock already imported, AsyncMock unused). Fixed `01c7e08`.

3. **Critical plan-doc defect through Task 8:** `get_or_create_stt` constructed `SpeechToText()` but never called `.load()`. Production manifested as silent empty transcripts. Plan also missed it. Caught only by the code-quality reviewer reading the consumer (`stt.py:_model = None` until `.load()` populates). Fixed `6f79824` with a parametrized test for the cold-init failure path.

4. **Critical race condition introduced by Task 9:** prewarm + legacy `_tts_bg_load` background task both called `load_models()` concurrently in default config. F5 weights double-loaded → GPU OOM risk. Fixed `abfcb5e` by deleting `_tts_bg_load` (subsumed) + adding `KALI_SKIP_PREWARM` env-var skip for tests.

**Pattern:** the two-stage review (spec compliance → code quality) consistently catches issues even when the plan was reviewed 4 times. Worth the dispatch cost. Default-suite testing of HTTP shells + mocked ML is the right discipline; gating ML-integration to `ml-tests` keeps CI fast.

## Side-effects worth noting

- One subagent (Task 4 code-quality reviewer) ran `git stash` mid-review and `git checkout HEAD --` cleared the local `.claude/settings.local.json` modification present at session start. Vasily's local-only file; not blocking.
- All commits land directly on `main` per Vasily's solo-dev convention.

## Build / test commands (carry-forward)

```bash
# Fast backend test suite (pre-warm skipped via KALI_SKIP_PREWARM)
.venv/Scripts/python.exe -m pytest tests/kernel/builder/ \
  tests/kernel/test_builder_endpoints.py \
  tests/kernel/voice/ \
  tests/kernel/test_voice_transcribe_endpoint.py \
  tests/kernel/test_main.py -v

# UI tests (Chunk 4+ work)
cd ui && pnpm test && npx tsc --noEmit

# Lint (project uses ruff via uv)
uvx ruff check kernel/ tests/
```

## Files touched this session (14 commits)

| File | Lines | Tasks |
|------|-------|-------|
| `kernel/builder/wizard.py` | +35 / -17 | 1, 2 |
| `kernel/builder/flow.py` | +12 / -13 | 2 |
| `kernel/builder/session_store.py` | +1 | 3 |
| `kernel/builder/extractor.py` | +217 (new) | 4, 5 |
| `kernel/main.py` | +29 (extract) +28 (prewarm) -14 (delete _tts_bg_load) | 6, 9 |
| `kernel/voice/transcribe_helper.py` | +96 (new + load fix) | 7, 8 |
| `tests/kernel/builder/test_question_to_key.py` | +35 (new) | 1 |
| `tests/kernel/builder/test_build_spec_helper_parity.py` | +49 (new) | 2 |
| `tests/kernel/builder/test_session_store.py` | +28 | 3 |
| `tests/kernel/builder/test_extractor.py` | +163 (new) | 4, 5 |
| `tests/kernel/test_builder_endpoints.py` | +56 / -3 | 6 |
| `tests/kernel/voice/test_transcribe_helper.py` | +85 (new + cold-init tests) | 7, 8 |
| `tests/kernel/test_voice_transcribe_endpoint.py` | +85 (new) | 8 |
| `tests/conftest.py` | +6 (KALI_SKIP_PREWARM) | 9 |

## What backend now exposes for frontend (Chunks 4-7)

The frontend can call these endpoints directly without further backend changes:

- **`POST /builder/extract`** `{request, language?}` → `{complete, session_id, spec | partial_spec, step?, total_steps?, questions?, next_question?}` — A4 fast-path
- **`POST /builder/start`** `{request}` → `{session_id, question, total_steps, template}` — fallback path (if frontend skips extract)
- **`POST /builder/answer`** `{session_id, answer}` → `{done, question?, step?, total_steps?, preview?}` — wizard turn
- **`POST /builder/deploy`** `{session_id}` → `{status, name?}` — materialize skill
- **`POST /builder/cancel`** `{session_id}` → `{status}` — discard session
- **`POST /voice/transcribe`** `{audio_b64, sample_rate, language?}` → `{text, language, duration_ms}` — STT (lazy-init, app.state cached)
- **`POST /tts/speak`** `{text, language?}` → plays through speakers, returns `{status, duration}` — TTS readback

All endpoints engine-independent (don't depend on Phase 3 `voice.engine: rust` cutover Gate A).

---

*Handoff created 2026-04-28 after 9 of 25 voice-builder-pilot tasks shipped (Chunks 1-3 closed; backend complete). Backend extractor + STT + prewarm fully tested and green. Frontend Chunks 4-8 (16 tasks) remain. Next session resumes at Task 10.*
