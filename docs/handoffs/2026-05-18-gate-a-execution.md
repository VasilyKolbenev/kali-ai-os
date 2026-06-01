# Gate A — Rust voice cutover execution guide

> Created 2026-05-18 during max-confidence debug session.
> **Blocked by:** wake-word working end-to-end (smoke test #1). Without working wake-word, the live rehearsal step can't be evaluated.
> Estimated execution time: 30 minutes.

## What Gate A is

The Tier 1 #7 task from the roadmap. Move KALI's voice pipeline from running through **Python orchestration** (`voice.engine: python` in `config/kali.yaml`) to **Rust orchestration** (`voice.engine: rust`). Rust backend already does VAD/STT/playback natively as part of Phase 3 of the migration; flipping the engine config makes Rust the default.

Closes Tier 1 entirely once committed.

## Prerequisites

Verify **all** before starting:

1. **Backend alive on :3005** (Python kernel for orchestration today):
   ```powershell
   Invoke-WebRequest -Uri "http://127.0.0.1:3005/health" -UseBasicParsing | Select -Expand Content
   ```
   Expect `"status":"ok"`.

2. **Rust :3006 alive** (this is what we'll cutover to):
   ```powershell
   Invoke-WebRequest -Uri "http://127.0.0.1:3006/health" -UseBasicParsing | Select -Expand Content
   ```
   Expect `"status":"ok"` from Rust.

3. **Wake-word works for you.** Smoke test #1 passing. If "Hey Jarvis" English doesn't trigger the orb pulse, do not proceed.

4. **Microphone working** (mic permission granted, audio device set correctly).

5. **TTS playback works** (you heard F5-TTS Russian voice respond to a chat message).

## Execution

### Step 1 — Read current engine config

```powershell
Get-Content C:\Users\User\Desktop\Jarvis\config\kali.yaml | Select-String -Pattern "engine|voice:"
```

Expect to see something like:

```yaml
voice:
  engine: python   # ← we will flip this to rust
```

If `engine` already says `rust`, Gate A is already closed — just verify by running the rehearsal below.

### Step 2 — Flip the config

Edit `C:\Users\User\Desktop\Jarvis\config\kali.yaml`:

```yaml
voice:
  engine: rust    # was: python
```

Save.

### Step 3 — Restart dev backend

In your PowerShell window where dev backend is running:

```
Ctrl+C
```

Then re-run:

```powershell
cd C:\Users\User\Desktop\Jarvis
$env:KALI_HOST = "127.0.0.1"
$env:KALI_PORT = "3005"
$env:KALI_CORS_ORIGINS = "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://localhost:1420,http://127.0.0.1:1420"
$env:KALI_WAKE_THRESHOLD = "0.15"
.\.venv\Scripts\python.exe -m kernel.main
```

Wait for `Uvicorn running on http://127.0.0.1:3005`.

### Step 4 — Live rehearsal

In the KALI UI window, do the canonical flow:

1. Say **"Hey Jarvis"** (English pronunciation).
2. Wait for orb pulse → state → `listening`.
3. Say **"Какая погода?"** (or any chat-style question).
4. Watch the pipeline:
   - STT transcribes your Russian
   - LLM answers
   - F5-TTS plays the answer through speakers
   - Orb returns to idle

**Success criteria** — all 4 substeps happen without you touching anything else.

If any substep fails → **STOP**. Don't commit. Log what failed and which substep. Do NOT proceed to step 5.

### Step 5 — Commit the cutover

Only if rehearsal passes end-to-end:

```powershell
cd C:\Users\User\Desktop\Jarvis
git add config/kali.yaml
git commit -m "feat(voice): cutover engine=rust default after live rehearsal"
```

Optionally tag for traceability:

```powershell
git tag tier-1-closed
```

### Step 6 — Update memory

Append to `memory/MEMORY.md` (or roadmap):

```
- 2026-05-XX: Tier 1 CLOSED. Gate A passed live rehearsal. config/kali.yaml voice.engine=rust committed (<short SHA>).
```

## What to do if rehearsal fails

| Symptom | Likely cause | Fix |
|---|---|---|
| Orb doesn't pulse after "Hey Jarvis" | Wake-word still not triggering | Smoke test #1 isn't actually passing; back to debug |
| Orb pulses but STT transcribes garbage | Whisper model on CPU + Rust pipeline mismatch | Compare against Python pipeline behavior — toggle `engine: python` back, re-test, isolate Rust vs Python |
| STT works but no LLM response | LLM key issue (404/401 in logs) | Re-check `OPENAI_API_KEY` in `.env`, validate via `/llm/test` |
| LLM responds in chat but no TTS playback | F5-TTS not loaded OR audio output device wrong | Check `/voice/status` `tts_loaded` field; check Windows default output device |
| Everything works but feels slower than Python pipeline | CPU bound — wake-word/STT/TTS running on CPU | Premium v3 build with onnxruntime-gpu fixes this (separate item) |

## Rollback

If you committed and then discovered a regression:

```powershell
cd C:\Users\User\Desktop\Jarvis
git revert HEAD  # creates a new commit reverting voice.engine to python
```

`config/kali.yaml` change is config-only; no migrations needed.

## Reference

- Rust pipeline implementation: `src-tauri/src/backend/` (Phase 3 of migration, closed 2026-04-28 with `82481b3`).
- Original migration plan: `memory/project_rust_migration.md`.
- This gate's parent: Tier 1 roadmap entry in `memory/project_roadmap.md` v2.15.
