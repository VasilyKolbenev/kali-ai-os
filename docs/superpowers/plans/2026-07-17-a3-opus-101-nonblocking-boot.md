# Plan: A3 / OPUS-101 — non-blocking Tauri boot

Дата: 2026-07-17. Ветка: `release/phase-a-desktop-alpha`. Статус: **PLAN + red-test design — ждёт утверждения владельца.**
Источник: аудит 2026-07-17 P0-02; adversarial-planning workflow (context7 Tauri v2 docs + 25 threats).
**OPUS-102 (Python lifespan / загрузка моделей) в этот блок НЕ входит** — это A4.

## Проблема (заземлено на коде + Tauri-доках)
- `src-tauri/src/lib.rs` `setup()` синхронно вызывает `start_backend()` (~243), который блокируется в `wait_for_backend_ready()` (82–90: 20×250ms = до 5с) до `Ok(())`. В Tauri v2 event loop не качает сообщения и **не рисует webview**, пока `setup` не вернётся → серое неотзывчивое окно (root cause A3-d).
- Rust axum (`serve()`, :3006) стартует в потоке **после** `start_backend` (246–254) → API/WS недоступны до окончания Python-ожидания (нарушает A3-b).
- Единственный emit `backend://failed` шлётся из блокирующего пути; в `App.tsx` нет `listen('backend://failed')` → **emit-before-listener теряется** (Tauri события не буферизуются для поздних слушателей).
- `BackendProcess(Mutex<Option<Child>>)` — только **внутрипроцессный** guard; второй запуск .exe = второй процесс с новым mutex → второе окно + попытка второго backend (спасает только TOCTOU-racy health-probe на :3005). A3-f требует cross-process guard.
- Нет restart-логики (нет storm, но и нет восстановления); child не в Job Object → hard-kill родителя оставляет orphan `kali-backend.exe` на :3005.

## Новый boot-sequence (non-blocking)
1. `run()`: захватить `t0 = Instant::now()` в самом верху, положить в managed state (для метрики first-paint).
2. Builder: `tauri_plugin_single_instance::init(...)` **первым плагином** — второй запуск сворачивается в primary (callback только фокусит окно `main`, backend-путь не трогает).
3. `manage()`: `BackendProcess` (без изменений) + новый `StartupCell { state: Mutex<StartupState>, shutting_down: AtomicBool, t0 }` (authoritative level-triggered состояние, initial = `ShellReady`).
4. `setup()` шаг 1: **первым** — spawn axum-потока (перенос существующего `thread::spawn(rt.block_on(serve()))`).
5. `setup()` шаг 2: spawn **supervisor-потока** (весь Python spawn + health-poll + backoff — вне main-треда).
6. `setup()` шаг 3: регистрация `CmdOrCtrl+Space`, `return Ok(())` **немедленно** (работа main-треда = bind+spawn+shortcut = суб-миллисекунда). Event loop качает, webview рисуется без ожидания Python.
7. Supervisor: poll :3006 → `RustReady`; `resolve_backend_path`==None → `Degraded{not_found}` (без spawn); под mutex `reap_tracked` (try_wait) → `spawn_decision(alive, healthy)`; на `Spawn` — резерв слота, **spawn вне lock**, ре-lock, проверка `shutting_down` (kill если да) иначе store; `PythonStarting`.
8. Steady state (~500ms/цикл): mutex держится только на быстрый reap/store, **никогда** через HTTP-probe/spawn. Живой-но-unhealthy child (30–60с загрузка моделей OPUS-102) → остаётся `PythonStarting` **без kill-deadline**. Healthy → `PythonReady` (emit только на смену).
9. Crash: `try_wait==Some` → reap; `next_backoff` (sliding window) → `Some(delay)` → sleep+respawn (bounded) / `None` → единый терминальный `Degraded`, respawn прекращается (no storm).
10. `get_startup_state` #[command]: возвращает состояние из `StartupCell` (level-triggered → пропущенный emit самолечится на следующем poll); фиксирует `t_paint` при первом вызове.
11. `stop_backend` (WindowEvent::Destroyed): `shutting_down=true` → lock → kill+wait. In-flight spawn при shutdown убивается, не оставляется orphan.

## Тестируемые seam'ы (pure `startup.rs`, std-only, без Tauri/ort)
| Seam | Сигнатура | Назначение |
|---|---|---|
| `StartupState` | enum `{ShellReady, RustReady, PythonStarting, PythonReady, Degraded{reason}, Failed{reason}}` | тотальное состояние; несёт **только** process-liveness, без model-progress (граница с OPUS-102) |
| `next_state` | `fn(cur: StartupState, ev: HealthEvent) -> StartupState` | чистая transition-функция; терминал поглощает поздние stale-события; `RustReady` предшествует любому `Python*` |
| `spawn_decision` | `fn(tracked_alive: bool, healthy: bool) -> SpawnDecision {Spawn\|SkipTracked\|SkipHealthy}` | truth-table без ambient IO (флаги передаёт caller) |
| `resolve_backend_path` | `fn(exe_dir: Option<&Path>, exists: impl Fn(&Path)->bool) -> Option<PathBuf>` | lift `find_backend` с инъекцией fs-probe → детерминируемая None-ветка (dev-box не маскирует missing-install) |
| `next_backoff` | `fn(attempt, failures_in_window, base, max, cap) -> Option<Duration>` | экспоненциальный capped delay; `None` за cap → терминал; **mutation-critical: не Some(ZERO)** |
| `reap_tracked` | `fn(&mut Option<Child>) -> bool` | try_wait → «tracked==alive»; чистит слот **до** `spawn_decision` (труп не глушит нужный restart) |
| `supervise_step` | `fn<P:HealthProbe,S:BackendSpawner,C:Clock>(ctx, probe, spawner, clock, emit) -> LoopControl` | тело supervision-цикла над инъектируемыми коллабораторами → все A3-поведения unit-drivable фейками |
| traits | `HealthProbe{healthy}` / `BackendSpawner{spawn,alive,kill}` / `Clock{now,sleep}` | развязка от ureq/Command/wall-clock; фейки гоняют виртуальное время |

`lib.rs` становится ~15-строчным адаптером (реальные ureq/Command/AppHandle.emit).

## Unit-тесты (red-first, mutation-noted)
1. `spawn_decision_truth_table` — 4 комбо точный вариант. Мут: инверсия любой ветки/безусловный Spawn → редён. (пиннит **cold first-run Spawn**, не только dev-box SkipHealthy).
2. `next_backoff_exact_schedule_and_giveup` — конкретное расписание, строго неубывающее, `None` ровно на `cap+1`. Мут: Some(ZERO) / всегда None / off-by-one cap. **← значения зависят от owner-ответа (restart policy).**
3. `next_state_transition_matrix` — полная матрица {states}×{events}; терминал поглощает; нет `Python*` до `RustReady`. Мут: убрать terminal-absorb / ordering.
4. `next_state_python_ready_idempotent` — два `PythonHealthy` → один переход (single emit). Мут: emit-on-tick → редён (анти-thrash).
5. `resolve_backend_path_candidate_order` — инъекция exists() → Premium/flat/None. Мут: reorder / убрать None-ветку (единственный guard missing-install).
6. `reap_before_decision` — reaped exited → Spawn; alive → SkipTracked. Мут: пропустить try_wait → zombie-never-restarts редён.
7. `supervise_loop_happy_sequence` — фейки → emit ровно `[RustReady, PythonStarting, PythonReady]`, spawn() ровно 1 раз. Мут: double-spawn/порядок.
8. `supervise_loop_crash_storm_bounded` — child умирает сразу + вирт-clock 60с → spawn ≤ cap, blip не сбрасывает счётчик, терминал Degraded, без busy-loop. Мут: reset-on-blip / игнор None.
9. `supervise_no_kill_while_alive` — alive+unhealthy >30с → `PythonStarting`, `kill()` НЕ вызван. Мут: добавить readiness kill-deadline → редён (защищает 30–60с OPUS-102 load).
10. `supervise_shutdown_kills_inflight` — `shutting_down` между spawn и store → child убит, не сохранён. Мут: безусловный store → orphan редён.
11. `get_startup_state_last_write_wins` — состояние `PythonReady` при ZERO слушателях (читает cell, не re-probe). Мут: re-probe :3005 → при fake-down редён (level-triggered self-heal).

## Live-верификации (против dev-machine-masking)
- **first-paint ≤1с**: pre-clean (taskkill :3005/:3006 + orphan); форс медленного пути `KALI_BOOT_DELAY_MS=45000` (только под `debug_assertions`, в child, не в shell); 5 запусков; `t0`=верх run(), `t_paint`=первый `get_startup_state` из webview; assert `(t_paint-t0) ≤ 1000ms` при `backend_is_running()==false`; p50/max в лог. **Cold обязательно** (иначе тёплый dev-box маскирует).
- **30–60с delay не серит окно**: `KALI_BOOT_DELAY_MS=45000`, интеракции (drag/click/scroll) все 45с; окно отзывчиво, React показывает **прогрессирующее** `PythonStarting`, НЕ терминальный red и НЕ ложный 5с-failure; затем `PythonReady`.
- **Rust API/WS сразу (Python-independent)**: убрать `kali-backend.exe`; WS `ws://127.0.0.1:3006/ws` + `GET :3006/health`==200 в пределах старта shell; `kernelStage`==0 (нет red на failMs=12000).
- **Degraded/offline честно**: убрать exe → окно рисуется, отдельная degraded-поверхность («backend not found» + log path), НЕ текст загрузки моделей, НЕ голое зелёное, НЕ серое.
- **Второй запуск — без второго backend**: запуск ×2 в пределах 200ms → ровно один `kali-backend` PID, второй invocation **фокусит** окно `main`. Повтор во время cold-start (cross-process SkipHealthy backstop).
- **Crash/restart контролируем**: (a) taskkill PID после PythonReady → supervisor respawn **ровно раз**, назад в PythonReady; (b) crash-loop (missing models dir) 30с → spawn ≤ cap, единый settled Degraded без мигания, CPU не пиковый.
- **Shutdown mid-spawn без orphan**: закрыть окно ~200ms (окно spawn) → ноль `kali-backend`, :3005 свободен; закрыть ~1с cold → `stop_backend` <100ms (mutex не держится через IO).
- **get_startup_state отзывчив + late-listener self-heal**: hammer 10ms — каждый <50ms; поздний listener в момент healthy → UI сходится к `PythonReady` за один poll.

## Файлы
- **NEW** `src-tauri/src/startup.rs` — pure leaf (enums, next_state, spawn_decision, resolve_backend_path, next_backoff, reap_tracked, traits, supervise_step) + `#[cfg(test)]`. std-only, ≤800 строк, функции ≤50.
- `src-tauri/src/lib.rs` — `mod startup;`; t0; single-instance первым; StartupCell; setup: axum первым → supervisor-поток → shortcut → `Ok(())` (убрать синхронный `start_backend`); `start_backend` → spawner-адаптер; `get_startup_state` #[command]; `stop_backend` ставит `shutting_down`; invoke_handler += get_startup_state.
- `src-tauri/Cargo.toml` — `tauri-plugin-single-instance = "2"`.
- **NEW** `ui/src/hooks/useStartupState.ts` — mount: `listen('startup://state')` затем `invoke('get_startup_state')` (poll-beats-race) + низкочастотный reconciliation-poll; НЕ трогает `useOnboardingGate.slow`.
- `ui/src/App.tsx` — рендер degraded/failed поверхности (not-found/crashed/gave-up), отдельно от model-loading copy; первый `get_startup_state` = маркер first-paint.
- `src-tauri/capabilities/*.json` — проверить, что webview может invoke `get_startup_state` (в v2 команды приложения доступны своему webview по умолчанию).

## Commit-слайсы (после утверждения)
1. `feat(desktop): pure startup module + red-first unit tests` — `startup.rs` + полный `#[cfg(test)]` (+ documented mutation run); в lib.rs не вшито; `cargo test startup::` зелёный. ort-independent логика.
2. `fix(desktop): non-blocking boot — return from setup immediately` — переупорядочить lib.rs (axum первым, supervisor-поток, StartupCell, get_startup_state, t0/t_paint, shutting_down); убрать синхронный wait. **Чинит серое окно (a,b,c,d,g).**
3. `feat(desktop): single-instance guard` — plugin первым (callback фокусит `main`); mutex+SkipHealthy как belt-and-suspenders. (f).
4. `feat(ui): honest boot/degraded surface` — useStartupState + App.tsx distinct states, отдельно от model-loading. (e) + граница A3/OPUS-102.

## Риски / rollback
- **ort-sys gate (P1-02)**: `cargo test` строит весь crate → может упасть на ort-download на чистом/offline runner → тесты `startup.rs` не **исполнятся**. Митигация: `startup.rs` = истинный std-only leaf (позже liftable в под-crate); CI считает build-fail RED (не skip) + assert non-zero test count на cache-cleared runner. На dev-box (ORT кэширован) тесты идут.
- **Orphan на hard-kill**: child всё ещё не в Job Object → hard-kill родителя оставляет orphan. `shutting_down` улучшает graceful shutdown, но не гарантирует no-leak на hard-kill. → open question.
- **engine=rust bind-ordering**: `serve()` await'ит `build_pipeline_if_enabled()` (Python-мост) до `bind(:3006)`. В default engine=python — быстрый `Ok(None)`, :3006 биндится сразу; при engine=rust медленный мост задержит bind → kernelStage red на 12с. Вне lib.rs scope (voice/pipeline+ort). → open question.
- **single-instance vs deep-link init-order**: docs требуют single-instance до deep-link (deep-link сейчас нет; заметка на будущее).
- **Rollback**: каждый слайс независимо ревертится. commit 2 (макс value/risk) ревертится один, восстанавливая старый синхронный boot без трогания startup.rs/single-instance/UI. commits 1/3/4 аддитивны.

## Owner-решения (2026-07-17) — план decision-complete
1. **Restart policy: `250ms→500ms→1s→2s→4s`, give-up на 5 failures в окне 60с** → терминальный Degraded. Пиннит `next_backoff` тест #2: schedule=[250,500,1000,2000,4000]ms, `None` на attempt 6.
2. **Windows Job Object — fast-follow** (отдельный блок после A3). A3 даёт graceful shutdown (`shutting_down`); zero-orphan-on-hard-kill (`AssignProcessToJobObject(KILL_ON_JOB_CLOSE)`) — следующий малый блок. Live-протокол shutdown проверяет graceful путь, hard-kill orphan помечается known-gap до fast-follow.
3. **engine=rust bind-order — отложено в voice-трек.** A3 держит default engine=python (`serve()` → `Ok(None)` → :3006 биндится сразу, acceptance (b) выполняется). Перестановка bind-before-pipeline (backend/mod.rs + pipeline + ort) вне A3.
4. **Test-delay lever: `KALI_BOOT_DELAY_MS`, только под `debug_assertions`**, инъекция в child (не в shell/release). Финализирует live first-paint/30-60с протокол без чистки реального кэша.
5. **Degraded RU-copy** — предложу дефолты при commit 4 (три состояния: «backend не найден» / «backend упал, повтор…» / «не удалось запустить backend»), owner-апрув на месте.
