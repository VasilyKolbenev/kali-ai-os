# Premium v3 Rebuild — design spec

> Status: spec, draft v1. Created 2026-05-18 after maximum-confidence debug session.
> Roadmap slot: blocker for friend distribution. Estimated 1 day (build) + 0.5 day (verify).
> Driven by: 11 plan-defects caught during install/wake-word debug — Premium v2 install was unusable until manual workaround.

## One-line summary

Premium v3 installer that **works end-to-end out of the box** on a fresh Windows install — no manual file moves, no dev-backend workaround. Fixes 8 root causes discovered during 2026-05-18 systematic debug.

## Why v3 exists

Premium v2 (Apr 29 build) installed cleanly but the runtime stack was broken in 5 distinct places:
1. Tauri's `find_backend()` looked at wrong path → spawned old residue from `C:\Program Files\KALI\` instead of the freshly-installed v2 backend.
2. `agent_builder.py:75` used relative path `agents/custom` → PermissionError when CWD was a read-only install dir.
3. PyInstaller spec missed `transformers.pipelines` submodule (lazy import not detected by static analysis) → F5-TTS crashed on first load.
4. Bundled `onnxruntime` (CPU-only) instead of `onnxruntime-gpu` → wake-word ran on CPU (~5× slower), CUDA model warnings.
5. Silero VAD cache locking → fallback to energy-based VAD (lower quality).

Plus 3 UX/cleanup items:
6. Onboarding asks user to say "Джарвис, привет" but OpenWakeWord `hey_jarvis_v0.1` is English-trained — scores 0.019 for Russian vs 0.328 for English. User experience is broken regardless of any other fix.
7. `KALI_WAKE_THRESHOLD` env var not wired up — threshold hard-coded at 0.30, no easy way to tune.
8. Uninstaller leaves `C:\Program Files\KALI\kali-backend.exe` behind → Tauri fallback finds it and runs stale binary.

v3 ships all 8 fixes in a single rebuild.

## Anti-pivot check

All 8 fixes are voice/install infrastructure. **No** dev/design integration creep. Anti-pivot rule v2.14 holds.

## File-by-file changes

### Backend (Python)

**`kernel/agent_builder.py:1-15`** — ALREADY APPLIED 2026-05-18 (uncommitted, awaiting Lite rebuild verification).

```python
from kernel.runtime_paths import appdata_dir, is_frozen

CUSTOM_AGENTS_DIR = (
    appdata_dir() / "agents" / "custom" if is_frozen() else Path("agents/custom")
)
```

Rationale: dev mode keeps relative path (tests rely on it); bundled mode writes under `%APPDATA%\KALI\agents\custom` which is always writable.

**Verification:** run `make test` after change — all existing tests pass since `is_frozen()` returns False under pytest.

### Backend (PyInstaller spec — `scripts/build_backend_premium.py`)

Add these flags to the `cmd` list:

```python
# Force-bundle transformers submodules (lazy-imported by f5_tts.api).
cmd.extend(["--collect-all", "transformers"])
# Bundle torch with submodules — f5_tts pulls torchaudio/torchcodec lazily.
cmd.extend(["--collect-all", "torch"])
# Bundle Silero VAD trace files so torch.hub.load works offline.
cmd.extend(["--collect-data", "silero_vad"])
```

Replace in `pyproject.toml` (Premium-only optional dep section):

```toml
# Before
onnxruntime = ">=1.18.0"
# After (Premium has GPU)
onnxruntime-gpu = ">=1.18.0"
```

The CPU-only `onnxruntime` package conflicts when both are installed. Verify with `pip list` after build that only `onnxruntime-gpu` is present.

**Note:** Lite version stays on `onnxruntime` (CPU) — Lite is for users without GPU.

**Verification:** post-build, run `kali-backend.exe` manually from the install dir. Logs should show `OnnxruntimeExecutionProvider` = `CUDAExecutionProvider` (not Azure/CPU fallback).

### Backend (Wake-word — `kernel/voice/wake_word.py`)

**ALREADY APPLIED 2026-05-18.** Supports `KALI_WAKE_THRESHOLD` env var override + bumps wake-word scores above 0.05 from DEBUG to INFO logging. No further changes needed for v3.

### Tauri (`src-tauri/src/lib.rs:92-114`)

Replace `find_backend()`:

```rust
fn find_backend() -> Option<PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));

    let candidates = [
        // Premium v2+ install: bundled in kali-backend/ subfolder.
        exe_dir.as_ref().map(|d| d.join("kali-backend").join("kali-backend.exe")),
        // Lite NSIS install: backend flat next to kali-desktop.exe.
        exe_dir.as_ref().map(|d| d.join("kali-backend.exe")),
        // Dev mode: ../../../dist/kali-backend.exe relative to cargo target.
        exe_dir.as_ref().and_then(|d| {
            d.parent().and_then(|p| p.parent()).and_then(|p| p.parent())
                .map(|root| root.join("dist").join("kali-backend.exe"))
        }),
        // Last-resort PATH lookup.
        Some(PathBuf::from("kali-backend.exe")),
        // REMOVED: hardcoded C:\Program Files\KALI\kali-backend.exe fallback.
        // It pulls in stale residue from old installs and masks bugs in the
        // real install paths. If those break, fail loud rather than fall
        // back to whatever happens to sit in Program Files.
    ];

    candidates.into_iter().flatten().find(|p| p.exists())
}
```

Two changes:
1. Adds candidate `parent/kali-backend/kali-backend.exe` (the v2 Premium layout) **as the first candidate**.
2. Removes the hardcoded `C:\Program Files\KALI\` fallback — was the root cause of "Tauri spawns old residue" debug session.

**Verification:** after Rust rebuild, install Premium v3 on a clean VM. Confirm Tauri logs `Starting backend: <%LOCALAPPDATA%\Programs\KALI\kali-backend\kali-backend.exe>` (not `C:\Program Files\...`).

### Frontend (`ui/src/components/Onboarding/steps/MicTestStep.tsx:56`)

Replace the hardcoded prompt:

```tsx
// Before
state === "listening"
  ? "Скажи: «Джарвис, привет»"
// After — wake-word model is English-trained, score 0.019 for Russian "Джарвис".
state === "listening"
  ? "Скажи: «Hey Jarvis»"
```

Optionally also tweak `useOnboardingStore` flow text. The wake-word model rec test (`scripts/diag_wake_word.py` from 2026-05-18) confirms English "Hey Jarvis" reliably scores 0.30+.

**Long-term (separate spec, not v3):** train a custom Russian "Джарвис" model. See `memory/feedback_wake_word_russian.md` solution S4.

### Installer (`scripts/installer_premium.iss` — Inno Setup)

Add an uninstaller pre-step that cleans `C:\Program Files\KALI\`:

```inno
[Code]
function InitializeUninstall(): Boolean;
var
  OldDir: String;
begin
  Result := True;
  OldDir := 'C:\Program Files\KALI';
  if DirExists(OldDir) then
  begin
    if MsgBox('An older KALI install was found in ' + OldDir + #13#10 +
             'Remove it to prevent conflicts?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(OldDir, True, True, True);
    end;
  end;
end;
```

Same for `installer_lite.nsi` — add a `Section "Pre-Install Cleanup"` that detects and removes stale `C:\Program Files\KALI\` before installing fresh.

### Installer (`scripts/installer_lite.nsi:9`)

Change install dir from `$PROGRAMFILES64\KALI` (system-wide, admin) to `$LOCALAPPDATA\Programs\KALI` (user-level, no admin):

```nsis
; Before
InstallDir "$PROGRAMFILES64\KALI"
RequestExecutionLevel admin

; After — match Premium's user-level install. Avoids the Program Files
; permission issues that bit us in v2.
InstallDir "$LOCALAPPDATA\Programs\KALI"
RequestExecutionLevel user
```

**Side effect:** with `agent_builder.py` already patched to use `%APPDATA%\KALI\` for custom agents, this change is belt-and-suspenders. Keep both — the Lite install dir change makes the failure mode less likely to surface even if some other code path slips a relative path.

## Build sequence

```powershell
# 1. Verify all source patches applied (this spec's File-by-file section).
git status  # expect: agent_builder.py, build_backend_premium.py, lib.rs,
            # MicTestStep.tsx, installer_premium.iss, installer_lite.nsi,
            # pyproject.toml

# 2. Run tests — make sure nothing broke.
.venv/Scripts/python.exe -m pytest tests/kernel/ -q

# 3. Rebuild backend (Premium).
uv run --with pyinstaller python scripts/build_backend_premium.py
# Expected output: dist_premium/kali-backend/ (~8-9 GB onedir bundle)

# 4. Rebuild backend (Lite).
.venv/Scripts/python.exe scripts/build_backend_lite.py
# Expected output: dist_lite/kali-backend/ (~200 MB onedir bundle)

# 5. Rebuild Tauri (Rust target/ is empty after cleanup — first build is slow).
cd ui && pnpm install && pnpm build && cd ..
cd src-tauri && cargo build --release && cd ..

# 6. Premium installer.
scripts/build_installer_premium.bat
# Expected output: dist_premium/installer/KALI-Premium-Setup-0.2.0-beta.exe + 2 .bin

# 7. Lite installer.
& "C:\Program Files (x86)\NSIS\makensis.exe" scripts/installer_lite.nsi
# Expected output: dist_lite/KALI-Lite-Setup-0.2.0-beta.exe

# 8. Verify size + signature.
Get-ChildItem dist_premium/installer/ dist_lite/*.exe | Format-Table Name, Length, LastWriteTime
```

## Verification checklist (after rebuild)

Run on a **clean Windows VM** if possible (no leftover KALI state):

- [ ] Premium installer runs to completion without admin prompt
- [ ] Premium install dir at `%LOCALAPPDATA%\Programs\KALI\kali-backend\` exists
- [ ] Launch KALI → backend starts within 10 sec, `started: true` in /voice/status
- [ ] Onboarding screen shows "Скажи: «Hey Jarvis»"
- [ ] Say "Hey Jarvis" → orb pulses → STT transcribes → response with TTS playback
- [ ] No `transformers.pipeline` errors in `%APPDATA%\KALI\logs\kali-backend.err.log`
- [ ] CUDA provider active for wake-word (log: `OnnxruntimeExecutionProvider: CUDAExecutionProvider`)
- [ ] Restart KALI → onboarding NOT shown (persistence works)
- [ ] Uninstall → `C:\Program Files\KALI\` removed (if present)
- [ ] Reinstall over existing → no version conflicts

Repeat for Lite installer.

## Out of scope (parked for v4)

- Custom Russian wake-word model training (separate 1-2 day spec, see `memory/feedback_wake_word_russian.md` S4).
- ElevenLabs reference voice management UI improvements.
- Backend auto-recovery if it crashes mid-session (lib.rs `start_backend` is one-shot today).
- Signing the installers (Authenticode) — defer to public-launch sprint.
- Build script consolidation (`build_release.bat` is 0.1.0-only, doesn't know about v3).

## Risk register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| `--collect-all transformers` blows up bundle size > 5 GB | medium | medium | We're at 3.7 GB Premium; should land around 4-5 GB. Use `--collect-submodules` if too big |
| `onnxruntime-gpu` requires specific CUDA version | medium | high | Pin to a CUDA-12.8 compatible release; document in install README |
| Inno Setup `InitializeUninstall` runs before user gets a chance to cancel | low | medium | MsgBox confirmation — user can decline cleanup |
| New `find_backend()` order picks the wrong candidate during dev | low | low | Dev mode never has kali-backend.exe next to kali-desktop.exe; falls through to candidate #3 |
| MicTestStep text change breaks existing localized tests | low | low | Update test snapshots; English fallback is also more universally pronounceable |

## Estimated effort

- Code patches: 1-2 hours (apply file-by-file changes + run tests)
- Premium backend rebuild: 30 min (PyInstaller)
- Lite backend rebuild: 10 min (PyInstaller, smaller bundle)
- Tauri rebuild from clean: 15-30 min (Rust target/ was wiped during cleanup)
- Frontend rebuild: 1-2 min (`pnpm build`)
- Installer build: 5-10 min (Premium DiskSpanning + Lite NSIS)
- Verification: 30-60 min (smoke test on clean state)

**Total: 4-6 hours single-pass.**

Reuses the disciplined build pipeline already proven in v2. New code is small and localized.

## Reference files

- Root cause analysis: `memory/feedback_wake_word_russian.md` (2026-05-18)
- Original Premium build script: `scripts/build_backend_premium.py`
- Test script for wake-word scores: `scripts/diag_wake_word.py`
- Tauri spawn logic: `src-tauri/src/lib.rs:92-185`
