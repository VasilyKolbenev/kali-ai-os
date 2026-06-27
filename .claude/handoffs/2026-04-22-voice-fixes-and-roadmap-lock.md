---
handoff_date: 2026-04-22
project: KALI — Personal AI OS
branch: main
latest_commit: 03ec9b2
version: 0.2.0-beta
continues_from: 2026-04-21-kali-0.2.0-beta-post-release.md
---

# KALI Handoff — 2026-04-22 — Voice Fixes + Full Roadmap Lock

## Current State Summary

**Major milestones reached this session:**

1. **Product vision pivoted + locked.** KALI repositioned from "voice-first Agent Skills client" → **"voice-first AI agent CREATOR for non-tech users"** (строитель, врач, офисный работник 30+). Distribution thesis = UGC viral loop (create → share reel → friends install). 10-item roadmap confirmed with user, all stubs written.

2. **TTS stack fully reworked.** Legacy Silero+RVC+DirectML completely removed. F5-TTS + ElevenLabs is sole prod path. A/B winner (04_v2ref_aggressive: cfg=3.5, nfe=64, speed=1.0, `jarvis_ref_v2.wav`) promoted. Russian text preprocessor (ruaccent + punctuation + number expansion) added and integrated. ElevenLabs voice clone recreated with 12 × 48kHz refs (new voice_id `7thl3XIdm0zimasgEzFv`).

3. **Voice-builder-pilot SHIPPED.** All 5 chunks from `docs/superpowers/plans/2026-04-22-voice-builder-pilot.md` executed and committed (SessionStore, BuilderFlow, HTTP endpoints, voice pipeline integration, UI panel, E2E test under 60s). This happened in parallel with the TTS work.

4. **Critical TTS runtime bugs fixed:** `_models_dir()` resolver now handles InnoSetup layout (`{app}/models/` one level above exe); file-based logger writes to `%APPDATA%/KALI/logs/kali-backend.log` (was stdout-only, lost under Tauri).

5. **Premium installer rebuilt with InnoSetup** (replaces broken 7z SFX). Multi-slice output: 1 exe + 3 .bin totalling 4.6 GB in `dist_premium/installer/`. Distribution-ready **only for tech-friends** — TIER 1 blockers (onboarding, settings UI, feedback) still pending before non-tech distribution.

6. **C4 architecture docs written** (Context + Containers + 2 Component diagrams) in PlantUML format. Live at `docs/architecture/`.

**Current active work:** user testing A/B accent configs 06/07 from `tools/tts_tune.py`. No blocking issues open.

## Important Context

### Critical environment facts (carry-forward from previous handoff)
- **OS:** Windows 11 (paths use both forward/back slashes)
- **User's GPU:** NVIDIA RTX 5070 Laptop (Blackwell, sm_120) — torch cu128
- **Python:** 3.12 via uv; system Python 3.14 for utilities
- **Shell:** bash for Claude tools, PowerShell/cmd for user
- **Repo:** `github.com/VasilyKolbenev/kali-ai-os` on `main`

### Working rule set (NEW — established this session)
- **"Предложи → обсудим → сделаем"** — when I see a missing feature/gap, PROPOSE it for discussion first, do not silently implement. This was explicitly requested by user.
- **Documentation commits** (docs/, memory/) can be made without asking.
- **Feature/refactor commits** wait for explicit "go".
- **No PR review** — solo dev, we commit directly.

### Credentials status
- **OpenAI API key** — in `%APPDATA%\KALI\.env` as `OPENAI_API_KEY`
- **ElevenLabs API key** — added to `.env` this session (user provided during ElevenLabs recreate). User may rotate after testing — if rotated, re-save.
- **New ElevenLabs voice_id** `7thl3XIdm0zimasgEzFv` saved to `%APPDATA%\KALI\elevenlabs_voice_id.txt` (replaces old `LuMAgLODaXoM7gaV55sV`).
- Backend logs now live at `%APPDATA%\KALI\logs\kali-backend.log` (5 MB rotating × 5).

### User working style
- Prefers Russian for conversation, English for code/paths
- Values production polish ("не прототип, а продукт для миллионов")
- Wants JARVIS canon feel in UI copy and naming
- Frustrated when we "collect new installer 40 min and waste time" — verify before rebuild
- Big appetite for strategic discussion (roadmap / positioning / investor criteria). Willing to pause coding to align.

## Key Architecture Decisions (new in this session)

| Decision | Rationale | Where locked |
|---|---|---|
| Product thesis = voice-first for non-tech (строитель/врач/офисник) | Differentiates from Cursor/Raycast/Copilot (dev tools). UGC reels = distribution engine. Solo-founder moat via niche. | `memory/project_vision.md`, `VISION.md` rewrite |
| Naming for Dashboard → **"Цифровой статус"** | Rejected: Brifing, Сводка (generic), JARVIS-canon "Status" with "Цифровой" HUD-vibe | `memory/project_roadmap.md`, stub `docs/superpowers/plans/2026-05-01-tsifrovoy-status.md` |
| Holographic design: **Level 1 + cherry-pick Level 2** | Level 3 full-3D deferred until 100+ active users. Avoid gimmicky fan-art feel. | stub `docs/superpowers/plans/2026-04-26-holographic-design-tokens.md` |
| Anti-Marvel vocab: "Ядро KALI" / "Интерфейс" / "Контур" | Avoid direct Stark/Arc Reactor licensing risk | same stub + stored in roadmap memory |
| TIER 1 BLOCKERS (onboarding, settings UI, feedback) gate non-tech distribution | Without these 3, friends install and churn in <60s. Only tech-friends comfortable with .env editing can test now. | `memory/project_roadmap.md` |
| F5-TTS A/B winner params: cfg=3.5, nfe=64, speed=1.0, `remove_silence=False`, ref=`jarvis_ref_v2.wav` | User-approved on `04_v2ref_aggressive.wav` output | commit `677a87c` |
| Russian text preprocessing pipeline (ruaccent + punct + numbers) | F5 without stress marks guesses wrong; punctuation affects prosody; numbers mispronounced | commit `19d1769` + `03ec9b2` (onnxruntime) |
| Agent Store = "App Store + TikTok", not flat list | Discovery surface must have hero/featured/categories/installed-shelf/details-modal | stub `docs/superpowers/plans/2026-04-30-agent-store-v2.md` |
| InnoSetup DiskSpanning for Premium installer (>4 GB) | 7z SFX is 32-bit Intel i386 → fails on >4 GB payloads | commit `d00d7b0` + `34d18d0` |

## Confirmed Roadmap (ordered)

| # | Plan file | Size | Status |
|---|---|---|---|
| 1 | `2026-04-22-voice-builder-pilot.md` | 3-5д | ✅ **DONE** (shipped in parallel with TTS work) |
| 2 | `2026-04-26-holographic-design-tokens.md` | 2-3д | ⏳ stub, pre-requirement for surface-redesigns |
| 3 | `2026-04-27-onboarding-flow.md` | 3-4д | ⏳ stub, **TIER 1 BLOCKER** |
| 4 | `2026-04-28-settings-ui.md` | 2-3д | ⏳ stub, **TIER 1 BLOCKER** |
| 5 | `2026-04-29-feedback-channel.md` | 2-3д | ⏳ stub, **TIER 1 BLOCKER** |
| 6 | `2026-04-30-agent-store-v2.md` | 7-10д | ⏳ stub, main discovery surface |
| 7 | `2026-05-01-tsifrovoy-status.md` | 3-5д | ⏳ stub, replaces Dashboard |
| 8 | `2026-04-23-templates-gallery-v2.md` | 1-2д | ⏳ stub |
| 9 | `2026-04-24-share-to-reels.md` | 4-5д | ⏳ stub |
| 10 | `2026-04-25-agent-python-generation.md` | 3-5д | ⏳ stub, re-enable after 2 weeks stable skills |

Total estimate: ~60-70 дней solo (~3 months).

## Pending Work

### Immediate (next session first tasks)

1. **User tests A/B accent configs 06/07** from `tools/tts_tune.py` — comparing to approved `04_v2ref_aggressive.wav`. If accents improve — preprocessor stays in prod; if worse — set `KALI_TTS_ACCENT=0` to disable (punct+numbers still apply rule-based).

2. **If voice quality acceptable: begin Chunk 1 of Plan 2** — `holographic-design-tokens`. Shared token foundation needed before Agent Store v2 / Цифровой статус.

3. **Rebuild Premium installer** (~40 min) at a convenient time to bake in the F5 resolver fix + file logger + preprocessor. Current installed Premium still falls back to ElevenLabs because `_models_dir()` bug is compiled into the shipped exe. User workaround: `xcopy` models → `kali-backend/models/` — but rebuild is the proper fix.

4. **Verify ruaccent model downloads cleanly** on a fresh Premium install. Depends on HuggingFace reachability at first run.

### Nearest checkpoint
After Tier 1 blockers (#3-5) ship, KALI can be distributed to **non-tech friends** without `.env` editing. Before then — only tech-savvy testers.

### Follow-ups logged in roadmap
See "Confirmed Roadmap" table above. Each plan has a stub in `docs/superpowers/plans/`.

## Critical Files (new/changed this session)

### Backend voice
- `kernel/voice/tts_engine_f5.py` — `_models_dir()` now searches `exe_dir/models`, `exe_dir.parent/models`, `appdata/models`; added `_get_processed_reference_text()` to match ref_text to gen_text preprocessing
- `kernel/voice/text_preprocessor.py` — **NEW** — punctuation/numbers/ruaccent pipeline; opt-out via `KALI_TTS_ACCENT=0`
- `kernel/voice/tts_engine_elevenlabs.py` — unchanged this session but relevant (used by fallback path when F5 fails)
- `kernel/voice/pipeline.py` — now calls BuilderFlow when `_detect_builder_trigger()` matches ("создай/сделай агента/скилл"); multi-turn voice answers; yes/no deploy confirm (commits 5bd3d98, 2053e1a)

### Backend builder (all NEW this session — from pilot execution)
- `kernel/builder/session_store.py` — in-memory wizard state, 30-min TTL
- `kernel/builder/flow.py` — BuilderFlow orchestrator (start/answer/deploy/cancel)
- `kernel/main.py` — `/builder/*` endpoints added, BuilderFlow on app.state

### Backend entry
- `kernel/entry.py` — **rewrote** `_setup_logging()` — RotatingFileHandler to `%APPDATA%\KALI\logs\kali-backend.log` (5 MB × 5 rotations)

### Skills catalog
- `kernel/skills/catalog.py` — added `source_type="aggregator_json"` support, NeuralDeep registered as default source (42 RU skills live-verified)

### Tools
- `tools/tts_tune.py` — added configs 06/07 with `accents=True` + `sys.path` fix for `uv run --with` isolated envs
- `tools/tts_compose_reference.py` — composed `jarvis_ref_v2.wav` (unchanged, referenced for context)
- `tools/elevenlabs_recreate_clone.py` — **NEW** — rebuilds IVC clone from 12 × 48kHz Sound Pack clips

### UI (voice-builder pilot)
- `ui/src/api/builder.ts`, `ui/src/stores/builder.ts`, `ui/src/components/Builder/` — from commit 93ce613

### Installer
- `scripts/installer_premium.iss` + `scripts/build_installer_premium.bat` — InnoSetup config, DiskSpanning multi-slice, 2.1 GB slice size, WebView2 bootstrapper via external `install-webview2.ps1`
- `scripts/build_backend_premium.py` — added `ruaccent`, `onnxruntime`, `kernel.voice.text_preprocessor` to HIDDEN imports

### Deps
- `pyproject.toml` — added `ruaccent>=1.5`, added `onnxruntime` back (needed by ruaccent for ONNX ML model), removed `onnxruntime-directml`/`faiss-cpu`/`piper-tts` earlier in session
- `uv.lock` — regenerated

### Architecture docs (NEW)
- `docs/architecture/README.md` + 6 files: `c4-context.{md,puml}`, `c4-containers.{md,puml}`, `c4-components-backend.{md,puml}`, `c4-components-voice-builder.{md,puml}`, plus `voice-builder-state-machine.puml` and `voice-builder-dynamic.puml`

### Roadmap stubs (all NEW)
- `docs/superpowers/plans/2026-04-26-holographic-design-tokens.md`
- `docs/superpowers/plans/2026-04-27-onboarding-flow.md`
- `docs/superpowers/plans/2026-04-28-settings-ui.md`
- `docs/superpowers/plans/2026-04-29-feedback-channel.md`
- `docs/superpowers/plans/2026-04-30-agent-store-v2.md`
- `docs/superpowers/plans/2026-05-01-tsifrovoy-status.md`

### Memory (user's persistent notes — see MEMORY.md)
- `memory/project_vision.md` — rewritten with new thesis
- `memory/project_roadmap.md` — NEW — confirmed 10-plan order + Tier 1 blocker annotation
- `memory/feedback_tts_stack.md` — updated (Silero+RVC removed, F5+ElevenLabs confirmed)
- `memory/MEMORY.md` — index refreshed

## Key Patterns Discovered

### F5-TTS integration quirks
- **Reference text must match the preprocessing style of gen_text.** If gen_text gets ruaccent stress marks but ref_text doesn't, F5 produces inconsistent output. Solution: cached `_reference_text_processed` in `tts_engine_f5.py`.
- **PyInstaller onedir layout for models:** installer puts `kali-backend/` and `models/` at same level in `{app}`, NOT nested. Resolver MUST check `exe_dir.parent/models`.
- **ruaccent requires onnxruntime at runtime** — if removed from deps (because "we don't need CUDA directml"), ruaccent fails silently and falls back to no-accent output. Commit `03ec9b2` added it back.

### InnoSetup gotchas
- `SolidCompression=yes` + `DiskSpanning=yes` = incompatible. Solid stream can't be split. Must set `SolidCompression=no` when using disk spanning.
- `{GUID}` constants inside `[Run]` Parameters: InnoSetup parses `{...}` as its own constants → GUID in PowerShell literal breaks the compile. Workaround: move PowerShell logic into an external `.ps1` file.
- `iscc.exe` user-scope install path is `%LocalAppData%\Programs\Inno Setup 6\iscc.exe`, not Program Files.
- `WizModernImage-IS.bmp` and sibling wizard-image files were renamed/removed in 6.7.1. Safe bet: omit `WizardImageFile`/`WizardSmallImageFile` — defaults look fine.

### ElevenLabs IVC quality drivers
- Total reference audio duration: minimum 30s (hard cutoff), ideal 60-90s
- Sample rate: 48 kHz native preferred; 22 kHz downsampled loses upper spectrum (8-16 kHz crystalness) needed for butler tone
- Style diversity matters — mix short confirms + medium announcements + long tech-speak

### Dev vs frozen path resolution
- Dev: `Path(__file__).parent.parent.parent / "models"` → `<repo>/models`
- Frozen: `sys._MEIPASS` present, `sys.executable` is the stub exe → check exe_dir AND exe_dir.parent
- Always log the resolved path at INFO level — saves hours of debugging on friend machines

## Potential Gotchas

1. **`tools/tts_tune.py` under `uv run --with`** needs `sys.path.insert` for `kernel.*` imports — the isolated venv doesn't see repo root by default. Same pattern applied to `demo_builder.py` in pilot. Use in any future tool that mixes kernel imports with external deps.

2. **ruaccent first use downloads ~100 MB ML model** from HuggingFace. Lazy-loaded via `@lru_cache` in `text_preprocessor._get_accenter()`. First `/tts/speak` after startup will be slower. No offline fallback bundled — if HF unreachable, accent step silently skipped (punct+numbers still apply).

3. **Premium installer ships 4 files**: `KALI-Premium-Setup-0.2.0-beta.exe` + `-1.bin` + `-2.bin` + `-3.bin`. ALL must be in the same folder for install. README.txt in `dist_premium/installer/` explains this to the end user. When sharing via Google Drive, upload the whole folder — don't zip only some files.

4. **Current Premium installer does NOT have resolver fix** — it was built before commit `480две e`. Users installing it today will hit F5 fallback to ElevenLabs unless they `xcopy` models into `kali-backend/models/` manually. Rebuild (~40 min) bakes the fix.

5. **Parallel-committed voice-builder-pilot** (commits b9ea078..424fc8e) has chunks 1-5 shipped, INCLUDING the UI BuilderPanel. Verify it runs end-to-end before starting the design-tokens plan — if UI/backend got out of sync with other session work, integration bugs are likely.

6. **JARVIS Sound Pack copyright** — 54 WAV files in `Jarvis Sound Pack от Jarvis Desktop/` are from the Iron Man game/movies. Used as reference for local voice cloning. OK for personal dev, risky at scale / commercial. Must be replaced with original recordings before public launch / investor demo.

7. **TTS sounddevice playback in dev-backend can be silent** on Windows — `sd.play()` doesn't always resolve default audio device when backend is launched via `uv run`. The `/tts` endpoint returns WAV bytes that can be piped to a file for verification (`curl ... -o test.wav`). Not a problem in compiled Premium via Tauri.

8. **`_models_dir()` lookup order matters.** Checks `exe_dir/models` FIRST, then `exe_dir.parent/models`. If user does the `xcopy` workaround (adds `kali-backend/models/`), the legacy candidate wins. That's fine — both paths resolve to valid files.

## Common Commands

```bash
# Run all voice/preprocessor tests
uv run --with pytest --with pytest-asyncio pytest tests/kernel/voice/ -v

# Run everything that mocks external services (no LLM/GPU needed)
uv run --with pytest --with pyyaml --with requests --with pytest-asyncio pytest tests/kernel/ -x

# Dev backend from source (includes all current fixes)
uv run python -m kernel.entry

# Rebuild Premium backend (~10 min) — run after any backend code change
uv run --with pyinstaller python scripts/build_backend_premium.py

# Rebuild Premium installer (~40 min LZMA2 ultra) — after backend rebuild
scripts\build_installer_premium.bat

# A/B voice tuning (7 configs → out/tts_tune/)
uv run --with f5-tts --with soundfile --with ruaccent python tools/tts_tune.py

# Only generate accent-enabled configs 06/07
uv run --with f5-tts --with soundfile --with ruaccent python tools/tts_tune.py --only accents

# Recreate ElevenLabs voice clone (needs ELEVENLABS_API_KEY in %APPDATA%/KALI/.env)
uv run --with soundfile --with scipy --with requests python tools/elevenlabs_recreate_clone.py --delete-old

# Verify TTS via file output (bypasses sounddevice quirks)
curl -X POST http://localhost:3005/tts -H "Content-Type: application/json" -d "{\"text\":\"Тест.\",\"language\":\"ru\"}" -o test.wav
```

## Test Status

- **33 tests** in `tests/kernel/voice/test_text_preprocessor.py` — all passing (punctuation / abbreviations / numbers / end-to-end flow)
- **Builder pilot tests** (from parallel commits) — not verified in this handoff, user should run before new work
- **Catalog tests** with NeuralDeep aggregator — all 20 passing (verified in commit `9490d5f`)
- **Full kernel suite** last run: 293/294 passing (1 pre-existing flaky `test_dispatch_tool_call`, unrelated to session work)

## Immediate Next Steps (for next agent)

1. **Greet user in Russian.** Acknowledge continuity from voice-tuning + roadmap-lock session.

2. **Ask what they heard from the A/B test** — configs 06/07 vs 04. Three outcomes:
   - Accents clearly better → promote preprocessor (already in prod via `_fix_text`), rebuild Premium at convenience
   - Accents worse/mixed → set `KALI_TTS_ACCENT=0` in `.env`, preprocessor keeps only punct+numbers. Document what sounds wrong.
   - Inconclusive → suggest more test texts with tricky RU words to localize the issue

3. **Verify voice-builder-pilot actually runs end-to-end** — was shipped in parallel, may have integration bugs:
   - Run `tests/e2e/test_builder_voice_e2e.py`
   - Manual: open Tauri shell (or dev mode) → Builder panel → "напомни пить воду каждые 2 часа" → should deploy under 60s

4. **Start holographic-design-tokens** (Plan 2) if voice is OK. This is pre-requirement for the 4 major surface redesigns (onboarding, settings UI, agent-store v2, цифровой статус). Follow `docs/superpowers/plans/2026-04-26-holographic-design-tokens.md`.

5. **Do NOT start any code work before verifying** user's current status (he may have tested more / raised new issues not captured here).

6. **Before rebuilding Premium installer** (40-min job), always confirm with user — he's explicit about not wasting time on unnecessary rebuilds.

## Communication Style for User

- **Russian for conversation**, English for code/paths/identifiers/commits
- **Short, concrete answers** — tables for comparisons, bulleted lists for plans
- **No emoji flood** — occasional ✅ / ⚠️ / 🎤 are fine, don't make it festive
- **Propose before implementing** anything non-trivial (new rule this session)
- **Flag blockers vs nice-to-haves** explicitly — user values knowing what gates distribution
- **Honest self-assessment** — if I haven't verified something, say so (don't pretend completeness)
- **Ask before long-running builds** (installers ~40 min, PyInstaller ~10 min)

## GitHub State

- Remote: `github.com/VasilyKolbenev/kali-ai-os.git`
- Branch: `main`
- Latest commit: `03ec9b2` (onnxruntime dep added by user)
- Tag still `v0.2.0-beta` — no new release tagged this session
- No open PRs
- Working tree clean except `.claude/settings.local.json` (local config, ignored)

## User's Strategic Vision (still the North Star)

> KALI = voice-first AI agent **creator** for non-tech users (строитель, врач, офисник 30+). Distribution via UGC reels in TikTok/Reels. Desktop (Studio for creators) → Mobile (Consumer for users) → Hardware device (CLIK + Starlink). Breakthrough over category-follower.

Monetization phases (from `project_roadmap.md`):
- Now → Q3 2026: Free + Pro $9.99/mo (cloud voice, priority LLM, private agents)
- Q4 2026+: KALI Device $399 + $9.99/mo subscription

Seed investor criteria checkpoint: K-factor > 1 + 50+ paying + D30 retention > 30% required before institutional seed round. Solo-founder path — Pieter Levels-style bootstrap pending validation of UGC loop.

---

*Handoff created 2026-04-22 21:11. Valid until significant changes are pushed. The voice-builder-pilot commits (b9ea078..424fc8e) happened in parallel with TTS work and should be verified as first action next session.*
