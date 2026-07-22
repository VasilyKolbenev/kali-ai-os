# Handoff — 2026-07-22 (Opus 4.8 / ultracode)

## TL;DR
- **OPUS-102 (non-blocking model boot) — CLOSED, Codex GO, принят как +5%. ЗАПУШЕНО.**
- Прогресс плана: общий **22%**; Phase A **22/30 = 73%**.
- `release/phase-a-desktop-alpha`: base `fbc34e9` → implementation tip `82bc6ec` (14 коммитов OPUS-102, все на origin).
- `main = origin/main = e3db43c` — protected, НЕ ТРОНУТ.
- Прогноз дедлайна 4–5 недель: **ON TRACK** (Phase A остаётся OPUS-103 3% + OPUS-201 2% = 5%).
- Следующий macro-batch: **OPUS-103 + OPUS-201 = ещё +5% — NOT STARTED** (ждёт plan-first → owner GO).

## VERIFY STATE (выполни первым делом, не доверяй SHA ниже)
```
git rev-parse --abbrev-ref HEAD                                   # release/phase-a-desktop-alpha
git rev-parse --short HEAD origin/release/phase-a-desktop-alpha main origin/main
git log --oneline origin/release/phase-a-desktop-alpha..HEAD      # пусто (всё запушено)
git status --short | grep -vE '^\?\?'                             # только pre-existing dirty
```
Зафиксированное на момент этого handoff: HEAD = origin/release = `82bc6ec`; main = origin/main = `e3db43c`.
Диапазон реализации OPUS-102: `fbc34e9..82bc6ec` (14 коммитов).

Pre-existing dirty (НЕ ТРОГАТЬ, не мои): `.claude/launch.json`, mobile codegen (5 файлов:
linux/windows registrant+cmake, macos GeneratedPluginRegistrant.swift), `ui/tsconfig.tsbuildinfo`, `uv.lock`.
Untracked: `scratchpad/` (evidence-файлы — оставить untracked, НЕ коммитить), логи/handoffs/daily.
Посторонний каталог `.audit_tmp_20260717/` (Permission denied в git status) — игнорировать.

## OPUS-102 — 14 коммитов (fbc34e9..82bc6ec)
```
82bc6ec fix(kernel): preserve terminal error on deadline-denied retry
b2f768b fix(kernel): refuse new heavy load past the operation deadline
7fe79ab fix(kernel): clear timed_out on a fresh load so retries aren't mislabelled
94469e4 fix(kernel): auto-start/voice-start share one bounded deadline; degraded on probe-false
f76f5d2 fix(kernel): probe-consistent completion + one absolute deadline
6c6c6ca fix(kernel): identity-guarded finalize + waiting warmup
2ba2421 refactor(kernel): waiting API for auto-start/routes/chat + deterministic evidence
08f5f51 feat(kernel): shared single-flight completion + bounded waiting API
07f7004 fix(kernel): dependency ensure waits for an in-flight shared dep
b557275 refactor(kernel): single voice owner + fail-closed routes + bounded shutdown
6620a2a feat(kernel): daemon-thread model loading with typed outcomes and deps
be54c90 fix(kernel): engine-scope on-demand voice load + clean task await
9d29e81 feat(kernel): non-blocking model boot + /live + /ready readiness
6c6e299 feat(kernel): single-flight ModelCoordinator with observable state
```
Последний коммит (`82bc6ec`) = terminal-error preservation microfix: deny-ветка `_acquire_load` больше НЕ
чистит `m.error`; existing terminal error сохраняется побайтово и отдаётся как FAILED (а не маскируется
TIMEOUT); clean-модель на expired deadline остаётся честным TIMEOUT; error чистится только fresh-retry'ем,
реально стартующим loader.

## Выполненные acceptance-критерии (все PASS, evidence в scratchpad/evidence)
1. **Non-blocking lifespan** — FastAPI lifespan не AWAITит F5-веса; текстовый режим не ждёт ML.
2. **/live и /ready** — `/live` мгновенный (zero ML/net); `/ready` = text_ready всегда True + voice snapshot.
   `GET /health` контракт Rust-супервизора НЕ тронут (200 + top-level `desktop_instance_id` + no-auth).
3. **Single voice owner** — `app.state.stt = pipeline._stt` (один STT-инстанс, не два).
4. **Shared single-flight completion** — конкурентные awaiter'ы ждут ОДНУ загрузку (`m.load_future`); один loader.
5. **engine=rust fail-closed** — voice-компоненты DISABLED при `voice.engine != "python"`; voice-роуты
   409 `engine_owned_by_rust`; никогда не зовут generate/get_or_create_stt после non-READY.
6. **Probe-consistent readiness** — loader вернулся, но authoritative probe=false → FAILED
   (`loader_completed_probe_false`), НЕ READY; поздний true-probe → recovery в READY без 2-го loader.
7. **Один абсолютный deadline** — `ensure_ready`/`ensure_all_ready`: deps+wait+loader берут remaining
   budget одного `deadline_at`, никогда не сбрасывается.
8. **Запрет нового loader после deadline** — pre-acquire guard внутри `m.lock` (await-free);
   `_DEADLINE_EXPIRED` sentinel по identity; loader НЕ стартует past deadline.
9. **Observable TIMEOUT/degraded** — status order probe→READY, error→FAILED, timed_out→TIMEOUT, thread→LOADING;
   `_voice_overall` FAILED/TIMEOUT → `degraded`.
10. **Bounded shutdown** — daemon-thread loaders (не `asyncio.to_thread`); `coordinator.shutdown()` +
    cancel/await task-wrappers; заблокированный loader не держит процесс (SLA ≤2с).
11. **Terminal error preservation** — deny-путь не маскирует реальный FAILED как TIMEOUT (`82bc6ec`).

## Финальные test counts (green)
- coordinator (`tests/kernel/test_model_coordinator.py`): **30**
- readiness wiring (`tests/kernel/test_readiness_wiring.py`): **17**
- shutdown (`tests/kernel/test_shutdown_process.py`): **1**
- **focused (три файла вместе): 48** — детерминизм подтверждён 3/3 свежих процесса (`-p no:cacheprovider`)
- voice (`tests/kernel/voice`): **70**
- main (`tests/kernel/test_main.py`): **57**
- core_loop (`pytest -m core_loop`): **13**
- `python -m scripts.release.version check` OK (1.0.0-rc3); `git diff --check` clean; Rust/UI не тронуты.

## Как гонять гейты (venv = .venv/Scripts/python.exe)
```
py=".venv/Scripts/python.exe"
$py -m pytest tests/kernel/test_model_coordinator.py tests/kernel/test_readiness_wiring.py tests/kernel/test_shutdown_process.py -q -p no:cacheprovider   # 48, ×3 свежих для детерминизма
$py -m pytest tests/kernel/voice -q          # 70 (медленно ~1-2мин)
$py -m pytest -m core_loop -q                # 13
$py -m pytest tests/kernel/test_main.py -q   # 57 (~1.5мин)
$py -m scripts.release.version check         # OK
git diff --check
```

## Residuals (не блокируют приёмку OPUS-102; закрыть позже)
1. **frozen `/live ≤1с` wall-time** — перепроверить на замороженном bundle в рамках **OPUS-103** (offline
   smoke на exact immutable stage; на dev-машине /live логически мгновенный, но frozen-время не измерено).
2. **VAD energy-fallback** — сейчас probe=false загрузка = FAILED/degraded; требуется отдельное
   **typed operational/degraded решение владельца** (energy-fallback как штатное operational-состояние, а не
   FAILED). Отложено — нужен явный state + продуктовое решение.
3. **Daemon loader физически не прерывается** — при shutdown loader-нить abandoned интерпретатором (не
   force-stop), НО процесс не удерживается (bounded SLA). Это by-design graceful, не дефект; зафиксировано.

## Контракты, которые НЕЛЬЗЯ ломать
- `GET /health` на :3005 → 200 + top-level string `desktop_instance_id` (== env `KALI_DESKTOP_INSTANCE_ID`)
  + без auth. Rust-супервизор (`src-tauri/src/lib.rs` RealProbe + `crash.rs` probe_backend_alive) зависит.
- Дефолт `voice.engine=python`, `auto_start=true`, `stt_model="small"` (kali.yaml не задаёт engine;
  models.py default python).
- `KALI_SKIP_PREWARM=1` в `tests/conftest.py` (тесты не грузят ML).
- Порядок регистрации роутеров в `kernel/main.py` «священен».

## Ключевые файлы OPUS-102
`kernel/model_coordinator.py` · `kernel/torch_dep.py` · `kernel/main.py` (lifespan voice-блок + prewarm/warmup
+ shutdown) · `kernel/routers/system.py` (/live,/ready,/health) · `kernel/routers/voice.py`
(_require_voice_model, /tts*, /voice/transcribe, /voice/start) · `kernel/routers/chat.py` (_speak_response) ·
`kernel/voice/transcribe_helper.py` (get_or_create_stt) · `tests/kernel/test_model_coordinator.py` ·
`tests/kernel/test_readiness_wiring.py` · `tests/kernel/test_shutdown_process.py`.

## Evidence-файлы (untracked, оставить локальными — НЕ коммитить)
- `scratchpad/evidence/2026-07-21-opus102-nonblocking-boot-evidence.md`
- `scratchpad/evidence/2026-07-21-opus102-fixloop-evidence.md`
- `scratchpad/evidence/2026-07-21-opus102-fixloop2-evidence.md`
- `scratchpad/evidence/2026-07-21-opus102-fixloop4-evidence.md`
- `scratchpad/evidence/2026-07-21-opus102-final-deadline-evidence.md` (исправлен: ложное «deny clears error»
  вычеркнуто + дат. CORRECTION → preserve-error контракт)
- `scratchpad/evidence/2026-07-22-opus102-terminal-error-preservation-evidence.md` (microfix + mutation-proof)
- `scratchpad/evidence/2026-07-21-opus202-opus301-plus5-evidence.md` (прошлый batch)

## Следующий macro-batch — OPUS-103 + OPUS-201 = +5% (NOT STARTED)
По PHASE A order из `docs/public-launch/2026-07-17-opus-4.8-session-start.md`:
- **OPUS-103 (3%)** — clean immutable staging + offline smoke на exact stage (`HF_HUB_OFFLINE=1`); закрывает
  residual #1 (frozen /live). Additive robocopy `/E` поверх premium_stage сохраняет удалённые/старые файлы —
  нужен clean immutable stage.
- **OPUS-201 (2%)** — fail-closed Windows signing + `signtool verify /pa`; отсутствие cert/signtool не должно
  давать зелёный (сейчас может молча пропуститься); обязательный post-sign verify.

Начинать: **plan-first (5–9 commits: evidence / файлы / изменение / red-тест / acceptance / rollback / что
требует cert-legal-account решения владельца) → дождаться owner GO → adversarial review → TDD → implement →
review → mutation-evidence → 3 fresh-process focused → стоп на Codex review.** НЕ пересобирать backend/installer
до stage-gate. НЕ начинать OPUS-301b (openai/google/deepseek), Product Evolution, #1c параллельно.

## Дисциплина (binding из session-start)
plan-first → adversarial review плана → RED-evidence → TDD → implement → review → fix-loop → mutation-evidence
(мутация → тест краснеет → revert). Малые commits, НЕ amend/force запушенного, НЕ в main. Stage только явные
пути; не add ./-A/reset/checkout/clean; не трогать pre-existing dirty. Merge/push в main — только после
phase-acceptance владельцем. fail-closed для signing/updater/native-UGC/version. Стоп на Codex review на каждом
гейте. Русский, кратко, с evidence.

## Готчи (перенос из прошлого handoff, актуальны)
- **git stale `index.lock`** (0-байт, от чужого фонового `git status`-поллинга IDE) блокировал запись. Проверить
  `Get-CimInstance Win32_Process`; если чужой read-only `git status`, снять ТОЛЬКО `.git/index.lock`.
- `torch` импортить только на worker/daemon-нити (frozen main-thread import падает); completion-gated probe.
- Reviewer ошибочно считал rust дефолтом — дефолт `voice.engine=python`, проверять эмпирически.
- git auto-gc печатает "too many unreachable loose objects" warning — benign housekeeping, не ошибка.
