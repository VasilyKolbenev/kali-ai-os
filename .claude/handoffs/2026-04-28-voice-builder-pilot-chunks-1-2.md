---
handoff_date: 2026-04-28
project: KALI — voice-builder-pilot v2 implementation
branch: main
latest_commit: 01c7e08
plan: docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md
spec: docs/superpowers/specs/2026-04-28-voice-builder-pilot-design.md
chunks_done: 2 of 8
tasks_done: 6 of 25
session_commits: 8 (6 feat + 2 fix)
---

# voice-builder-pilot v2 — Chunks 1-2 SHIPPED

## What this session delivered

**Chunk 1 — Backend foundation (3 tasks):**
- `989ea6e` Task 1: extract `_question_to_key` helper into `wizard.py` + 10-case parametrized test (the canonical question→config-key mapping; trigger BEFORE notify_channel ordering).
- `f04b0ad` Task 2: refactor both `WizardSession.build_spec` and `BuilderFlow._build_spec` to consume the helper + parity test (DRY; widens key namespace from 3 keys to 7 — `trigger`/`target`/`categories`/`time_window` no longer fall into `param_N`).
- `4c92f0a` Task 3: add `name_hint: str | None = None` field to `BuilderSession` dataclass + 2 tests (Task 2's `getattr` fallback now backed by a real attribute).

**Chunk 2 — Backend extractor (3 tasks + 2 lint fixups):**
- `3913d14` Task 4: `kernel/builder/extractor.py` skeleton with verbatim `LLM_SYSTEM_PROMPT` constant + `_call_llm` helper (lazy-imports `_detect_provider` and `_call_llm` from `agent_generator`, strips markdown fences, returns None on any failure).
- `d5ccf7e` Task 4 lint fixup: `# noqa: F401` on the 5 forward-compat imports (consumed by Task 5), `# ruff: noqa: E501` file-level (verbatim prompt has lines > 100 chars), drop dead `import pytest` from test, sort imports alphabetically.
- `e6505c3` Task 5: `extract_spec` + `_fallback_to_start` (5 unit tests covering complete extraction, two partial paths, invalid-template fallback, LLM-unavailable fallback). Two intentional ruff-driven deviations from plan-literal (merged `classify_intent` import at top vs in-function; dropped `BuilderSession` symbol since not source-named).
- `72250a4` Task 6: `POST /builder/extract` endpoint in `kernel/main.py` between `/builder/start` and `/builder/answer` (3 endpoint tests: complete-path, partial-path, rejects-empty).
- `01c7e08` Task 6 lint fixup: drop dead `from unittest.mock import AsyncMock, MagicMock` re-import (plan-driven defect).

**Test totals (all green):**
- `tests/kernel/builder/`: 30 passing (was 5 at session start).
- `tests/kernel/test_builder_endpoints.py`: 7 passing (was 4 at session start).

## What's next — Chunks 3-8 (19 tasks)

| Chunk | Tasks | Surface | Estimate |
|-------|-------|---------|----------|
| 3 | 7-9 | Backend STT endpoint — port `decode_and_resample` helper from `tts_worker.py:143-199`, add `POST /voice/transcribe` (in-process Whisper; lazy-init `app.state.stt`), F5 prewarm in FastAPI lifespan | ~1 day |
| 4 | 10-11 | Frontend foundation — extend `useBuilderStore` with new phases (listening / transcribing / extracting) + `editField` action + `previewSubState` + full `questions[]` field; extend `builderApi` with `transcribe`, `extract`, `say` | ~1 day |
| 5 | 12-14 | Frontend audio + orb — `useAudioCapture` (MediaRecorder blob + AnalyserNode polled live frames for VAD), `useRmsVad` (1.5s silence detection), `VoiceOrb` component | ~1.5 days |
| 6 | 15-18 | Frontend screen + layout — `LiveTranscript` + `SpecCard` + `WizardPrompt` (with TTS readback) + `VoiceBuilderScreen` (state-machine owner, L1 layout); replace `BuilderPanel`; `git rm` old Builder/ files; `git mv` StarterExamples | ~1.5 days |
| 7 | 19-21 | Frontend preview — `voiceCommands.ts` parser (whole-token equality cancel/confirm; substring for edit-field), `PreviewConfirm` (await-TTS gating), audio re-start between turns useEffect | ~1 day |
| 8 | 22-25 | Polish — first-mount mic-permission intro banner, error-recovery affordances, e2e Vitest, manual rehearsal (5 voice runs back-to-back, ≥4/5 success gate) + handoff doc | ~1 day |

Total ≈ 6-7 days remaining (matches the original 7-8 day estimate; first 2 chunks landed in 1 session).

## Continuation pattern for the next session

1. **Resume in a fresh session** (this one is approaching context limits — ~50 large subagent dispatches accumulated).
2. **Skill stack:** `superpowers:using-superpowers` → `superpowers:subagent-driven-development` (fresh subagent per task + two-stage review = spec compliance, then code quality).
3. **Read order on resume:**
   - This handoff (`.claude/handoffs/2026-04-28-voice-builder-pilot-chunks-1-2.md`)
   - The plan (`docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md`)
   - The spec (`docs/superpowers/specs/2026-04-28-voice-builder-pilot-design.md`)
   - Latest 8 commits (`git log --oneline -10`).
4. **Verify state before continuing:**
   ```bash
   .venv/Scripts/python.exe -m pytest tests/kernel/builder/ tests/kernel/test_builder_endpoints.py -v
   ```
   Expected: 30 + 7 = 37 passed.
5. **Start at Task 7** (Chunk 3, line ~956 in the plan): port `decode_and_resample` helper from `tts_worker.py:143-199` into `kernel/voice/transcribe_helper.py`.

## Patterns established this session

- **Two-stage review (spec compliance → code quality)** caught real defects: Task 4 added 9 ruff errors (mostly forward-compat imports the plan-spec mandated), Task 6's plan-text included a dead `unittest.mock` re-import, the spec/plan-doc reviews caught `app.state.stt` not being attached anywhere, etc. Worth the dispatch cost.
- **Lint-driven deviations from plan-literal are acceptable** — the implementer correctly merged imports at top (ruff E402) and dropped unused symbols (ruff F401) in Task 5. Document deviations in the implementer's report so the spec reviewer can verify they're functional-equivalent.
- **`# noqa: F401` for forward-compat imports**: when the plan mandates importing a symbol that won't be used until the next task, annotate inline so `make lint` stays clean. Drop the noqa when the consumer lands.
- **Verbatim prompt strings + ruff E501**: file-level `# ruff: noqa: E501` (with explanation comment) is the right tool for prompts that contain unsplittable long lines.
- **Each task = ~3 subagent dispatches** (impl + spec + code-quality). Trivial tasks can sometimes batch reviewers in parallel; complex tasks benefit from sequential review.

## Side-effects worth noting

- One subagent (Task 4 code-quality reviewer) ran `git stash` during its review and `git checkout HEAD --` cleared the local `.claude/settings.local.json` modification that was present at session start. Vasily's local-only file; not blocking. If the lost changes mattered, restore from editor history.
- All commits land directly on `main` per Vasily's solo-dev convention. No PRs, no worktrees.

## Build / test commands (carry-forward)

```bash
# Full backend test suite
.venv/Scripts/python.exe -m pytest tests/kernel/ -v

# Just builder + extractor + endpoints
.venv/Scripts/python.exe -m pytest tests/kernel/builder/ tests/kernel/test_builder_endpoints.py -v

# Lint (project uses ruff via uv)
uvx ruff check kernel/builder/extractor.py tests/kernel/

# UI tests (when Chunk 4+ lands)
cd ui && pnpm test && npx tsc --noEmit
```

## Files touched this session (8 commits)

| File | Lines | Tasks |
|------|-------|-------|
| `kernel/builder/wizard.py` | +35 / -17 | 1, 2 |
| `kernel/builder/flow.py` | +12 / -13 | 2 |
| `kernel/builder/session_store.py` | +1 | 3 |
| `kernel/builder/extractor.py` | +217 (new) | 4, 5 |
| `kernel/main.py` | +29 | 6 |
| `tests/kernel/builder/test_question_to_key.py` | +35 (new) | 1 |
| `tests/kernel/builder/test_build_spec_helper_parity.py` | +49 (new) | 2 |
| `tests/kernel/builder/test_session_store.py` | +28 | 3 |
| `tests/kernel/builder/test_extractor.py` | +163 (new) | 4, 5 |
| `tests/kernel/test_builder_endpoints.py` | +56 / -3 | 6 |

---

*Handoff created 2026-04-28 after 6 of 25 voice-builder-pilot tasks shipped (Chunks 1-2 closed). Backend foundation + extractor surface fully tested and green. Next session resumes at Task 7 (Chunk 3 — STT endpoint).*
