# Smoke test guide — KALI Premium v2 with dev-backend workaround

> Created 2026-05-18 after debug session.
> Purpose: confirm v2 install + workarounds actually deliver working voice + chat + agents end-to-end.
> Estimated time: 10-15 minutes.

## Recap — why we need dev-backend

Premium v2 binary backend has a `transformers.pipelines` PyInstaller bundling bug that prevents F5-TTS load → voice pipeline never starts. Workaround = run the backend from dev `.venv` (which has full `transformers`) and let Tauri UI connect to that. Premium v3 (separate spec) fixes this properly in the bundle.

## Step 1 — clean slate

```powershell
# Kill anything KALI-related still running
Get-Process | Where-Object { $_.ProcessName -like '*kali*' -or $_.ProcessName -like '*python*' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2

# Verify everything dead
Get-Process | Where-Object { $_.ProcessName -like '*kali*' }   # expect empty
Get-NetTCPConnection -LocalPort 3005 -ErrorAction SilentlyContinue  # expect empty
```

## Step 2 — start dev backend (PS window #1)

Open PowerShell window #1 and run:

```powershell
cd C:\Users\User\Desktop\Jarvis
$env:KALI_HOST = "127.0.0.1"
$env:KALI_PORT = "3005"
$env:KALI_CORS_ORIGINS = "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://localhost:1420,http://127.0.0.1:1420"
$env:KALI_WAKE_THRESHOLD = "0.15"
.\.venv\Scripts\python.exe -m kernel.main
```

**Do NOT close this window** for the duration of testing. Wait for these log lines (in order):

```
INFO  __main__: Loaded skill: water-tracker
INFO  kernel.database: Database initialized
INFO  __main__: Voice pipeline initialized
INFO  kernel.voice.wake_word: OpenWakeWord ready (wake_word=jarvis, threshold=0.15)
INFO  kernel.voice.stt: Whisper model loaded: base (cuda/float16)
INFO  kernel.voice.tts_engine_f5: F5-TTS ready                           ← critical
INFO  kernel.voice.tts_engine_f5: F5-TTS engine ready (reference: jarvis_ref_v2.wav)
INFO  kernel.voice.pipeline: Voice models loaded
INFO  kernel.voice.recorder: Audio recording started (rate=16000, chunk=512)
INFO  kernel.voice.pipeline: Voice pipeline started (mode=wake_word)
INFO  __main__: Voice pipeline auto-started (mode=wake_word, wake_word=jarvis)
INFO  kernel.voice.pipeline: Pipeline main loop started
INFO  Uvicorn running on http://127.0.0.1:3005
```

If you see `F5-TTS ready` and `Voice pipeline auto-started` — backend is fully up.

If you see `cannot import name 'pipeline' from 'transformers'` and no `F5-TTS ready` line — the dev env is missing transformers. Run `uv sync` (or `pip install transformers` inside `.venv`) and retry.

## Step 3 — verify backend state (PS window #2)

Open a SECOND PS window for diagnostics. Don't reuse #1.

```powershell
# Health check
Invoke-WebRequest -Uri "http://127.0.0.1:3005/health" -UseBasicParsing | Select -Expand Content

# Voice status — must have started=true, wake_word_loaded=true, tts_loaded=true
Invoke-WebRequest -Uri "http://127.0.0.1:3005/voice/status" -UseBasicParsing |
    Select -Expand Content | ConvertFrom-Json | ConvertTo-Json -Depth 3
```

Expected `/voice/status`:
```json
{
  "available": true,
  "ready": ...,            // may be false (missing RVC models — non-critical)
  "started": true,         // ← required for wake-word
  "state": "idle",         // listening when wake-word triggered
  "mode": "wake_word",
  "wake_word_loaded": true,
  "stt_loaded": true,
  "tts_loaded": true,      // ← was false on bundled v2; should be true on dev
  ...
}
```

If `started: false` → backend started but pipeline didn't auto-start. Force it:
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:3005/voice/start" -Method POST -UseBasicParsing
```

## Step 4 — launch KALI UI

In any PS window:

```powershell
& "$env:LOCALAPPDATA\Programs\KALI\kali-desktop.exe"
```

KALI window opens. It detects `:3005` already busy (your dev backend) → it does NOT spawn its own broken v2 backend. WebSocket connects (green dot top-left of sidebar).

If you see "Failed to fetch" — check PS #1, dev backend may have crashed. Fix and re-launch.

## Step 5 — run the 5 smoke checks

### ✅ #1 — Wake-word (English pronunciation)

The OpenWakeWord `hey_jarvis_v0.1` model is English-trained. Say:

> **"HEY JARVIS"** — clear English pronunciation, the "J" as in "Jack", not Russian "Дж"

Watch:
- Orb in KALI UI pulses → state → `listening`
- In PS #1 log: `Wake-word top score: hey_jarvis=0.XX (threshold=0.15)` and `Wake word detected: hey_jarvis`
- In PS #1 log: `Pipeline: idle -> listening`

If no orb pulse:
- Check log for score values. If you see `hey_jarvis=0.05-0.15` — model heard you but below threshold. Try louder/clearer.
- If no log lines at all — mic isn't capturing. Check Windows mic permission (settings → Privacy → Microphone → Desktop apps = On).
- If score stuck < 0.05 — environmental noise too loud OR mic gain too low.

### ✅ #2 — Chat with TTS playback

In KALI chat input (bottom), type:
> **"Привет, Джарвис"**

Expect:
- Text response appears in chat ("Привет, сэр..." or similar)
- **Voice plays through speakers** (F5-TTS Russian voice)
- Response tagged `llm-openai` in chat metadata

If text appears but no voice → `tts_loaded: false`, F5 didn't load. Restart dev backend.

If 401 LLM error → API key issue. Run:
```powershell
Get-Content C:\Users\User\Desktop\Jarvis\.env | Select-String "OPENAI_API_KEY"
```
Should be your project's OpenAI key. If different, run:
```powershell
Copy-Item "$env:APPDATA\KALI\.env" "C:\Users\User\Desktop\Jarvis\.env" -Force
```
Then restart dev backend.

### ✅ #3 — Onboarding persistence

Close KALI (X button). Reopen:
```powershell
& "$env:LOCALAPPDATA\Programs\KALI\kali-desktop.exe"
```

KALI should jump directly to main UI (HUD/avatar screen), NOT show onboarding again.

If onboarding shows again → `KALI_ONBOARDING_COMPLETED` env var lost. Check:
```powershell
Get-Content "$env:APPDATA\KALI\.env" | Select-String "ONBOARDING"
```
Should have `KALI_ONBOARDING_COMPLETED=true`. If false/missing → re-complete onboarding once, ensure it saves.

### ✅ #4 — AgentCard START + toast feedback

1. Click sidebar Agents tab (📋 or similar icon).
2. Find any agent (e.g. "calendar" or "weather") with **stopped** status.
3. Click **START** button on its card.

Expect:
- Button disables briefly during loading
- Toast notification appears: **"✓ calendar запущен. Напишите: 'события сегодня'"** (or similar)
- Toast disappears after 4 seconds
- Agent status changes to `running`

If no toast → AgentCard fix from v2 not applied. Check `ui/src/components/AgentPanel/AgentCard.tsx` — should have the toast logic (line ~80-120).

### ✅ #5 — Skills Refresh + Install

1. Click sidebar Skills tab.
2. Find "Anthropic Official" source row.
3. Click **Refresh** ↻ button.
4. Cards should appear (list of skills from Anthropic's catalog).
5. Click **Install** on any skill (e.g. "pdf").

Expect:
- Refresh shows loading state then card grid
- Install button shows progress → success message
- Skill appears in "Installed Skills" list

If Refresh hangs → network issue OR `/skills/catalog/refresh` endpoint not responding. Check PS #1 log for errors.

## Result — what to report back

After all 5:

```
✅ 1. Wake-word "Hey Jarvis" — passed (score = 0.XX)
✅ 2. Chat + TTS — passed
✅ 3. Onboarding persistence — passed
✅ 4. AgentCard toast — passed
❌ 5. Skills Install — failed (error: ...)

→ 4/5
```

| Score | Means | Next |
|---|---|---|
| 5/5 | All v2 fixes work end-to-end through dev backend | Proceed to Gate A + Gate B |
| 4/5 | Single regression — patch and re-test | Open chip for the specific failure |
| ≤3/5 | Multiple regressions — deeper investigation | Don't proceed; revisit Premium v3 plan |

## Known issues you may hit

- **Wake-word score 0.05-0.15** even with English "Hey Jarvis": background noise. Speak from <50cm to mic, repeat 2-3 times.
- **F5-TTS first call takes 5-10 sec**: model warmup, normal. Subsequent calls are fast.
- **Silero VAD energy fallback warning**: known issue, doesn't affect functionality.
- **CUDA provider not available warning**: dev `.venv` has CPU `onnxruntime`. Wake-word still works (CPU). Premium v3 fixes this.
- **Builder mode chat doesn't have wake-word activation**: that's expected — builder uses push-to-talk via mic button click.

## Reference

- Root-cause docs: `memory/feedback_wake_word_russian.md`
- Premium v3 spec: `docs/superpowers/specs/2026-05-18-premium-v3-rebuild.md`
- After smoke test passes: see Gate A (`docs/handoffs/2026-05-18-gate-a-execution.md`) and Gate B (`docs/handoffs/2026-05-18-gate-b-execution.md`).
