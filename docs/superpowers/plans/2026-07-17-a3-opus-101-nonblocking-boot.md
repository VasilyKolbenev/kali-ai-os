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
4. `setup()` шаг 1: **первым** — spawn axum-потока. **serve()/axum обязан отправить authoritative результат bind (`RustBindOk` | `RustBindErr(PortOccupied)`) из экземпляра ЭТОГО процесса** (через `std::sync::mpsc`/oneshot в supervisor). RustReady НЕ определяется poll-ом :3006 (poll увидел бы чужой/старый сервер → ложный RustReady).
5. `setup()` шаг 2: spawn **supervisor-потока** (единственный spawner Python; health-poll + backoff — вне main-треда).
6. `setup()` шаг 3: регистрация `CmdOrCtrl+Space`, `return Ok(())` **немедленно**. Event loop качает, webview рисуется без ожидания Python.
7. Supervisor Rust-gate: ждёт bind-сигнал. `RustBindErr(PortOccupied)` (наш :3006 занят чужим/старым процессом) → **`Failed/Degraded(PORT_OCCUPIED)`, НИКОГДА RustReady**. `RustBindOk` → `RustReady`.
8. Supervisor Python-gate: `resolve_backend_path`==None → `Degraded(NOT_FOUND)` (без spawn). Иначе `reap_tracked` (try_wait → alive) **до** решения → `spawn_decision(tracked_alive, healthy)`:
   - `(false,false)` → **Spawn** (порт свободен, нашего child нет);
   - `(true, _)` → **SkipAliveChild** (наш child жив — не плодим второй; Ready/Starting решает state);
   - `(false,true)` → **ForeignBackend** → `Degraded(FOREIGN_BACKEND)` — :3005 держит чужой/stale процесс, мы им НЕ владеем: **ни Ready, ни spawn**.
   Supervisor — строго один поток → «резервирование слота» не нужно; spawn под mutex, `shutting_down` проверяется до store.
9. Ownership-инвариант: **`PythonReady` допустим ТОЛЬКО когда tracked child жив И его health успешен.** healthy без tracked child ≠ Ready (см. ForeignBackend).
10. Steady state (~500ms/цикл): mutex — только быстрый reap/store, **никогда** через HTTP-probe/spawn. Живой-но-unhealthy child (30–60с OPUS-102) → `PythonStarting` **без kill-deadline**. Healthy+owned → `PythonReady` (emit на смену).
11. Crash: `try_wait==Some` → reap; `next_backoff` (окно 60с) → `Some(delay)` sleep+respawn (bounded) / `None` → терминальный `Degraded`, respawn прекращается.
12. `get_startup_state` #[command]: состояние из `StartupCell` (level-triggered → пропущенный emit самолечится); фиксирует `t_paint`.
13. **Lifecycle: идемпотентный `stop_backend` на `RunEvent::ExitRequested`/`Exit`** (`shutting_down=true` → lock → kill+wait; повторный вызов безопасен). `WindowEvent::Destroyed` — только ДОПОЛНИТЕЛЬНЫЙ сигнал, не единственный. In-flight spawn при shutdown убивается.

## Тестируемые seam'ы (pure `startup.rs`, std-only, без Tauri/ort, **без concrete `std::process::Child`**)
| Seam | Сигнатура | Назначение |
|---|---|---|
| `StartupState` | enum `{ShellReady, RustReady, PythonStarting, PythonReady, Degraded{reason: DegradedReason}, Failed{reason: String}}` | тотальное состояние; **только** process-liveness, без model-progress (граница OPUS-102) |
| `DegradedReason` | enum `{PortOccupied, ForeignBackend, NotFound, Crashed, GaveUp}` | машинная причина degraded/failed; UI мапит 1:1 |
| `HealthEvent` | enum `{RustBindOk, RustBindErr, ExeMissing, PythonHealthyOwned, PythonUnhealthyAlive, PythonExited, ForeignHealthy, GaveUp}` | вход `next_state`; **`RustBindErr`→Failed(PortOccupied)**; `ForeignHealthy`→Degraded(ForeignBackend); `PythonHealthyOwned` (только owned!) →PythonReady |
| `next_state` | `fn(cur: StartupState, ev: HealthEvent) -> StartupState` | чистая transition; терминал поглощает stale; `RustReady` предшествует `Python*`; `RustBindErr` → терминальный Failed |
| `spawn_decision` | `fn(tracked_alive: bool, healthy: bool) -> SpawnDecision {Spawn\|SkipAliveChild\|ForeignBackend}` | truth-table без ambient IO. **`(false,true)`→ForeignBackend (не Spawn, не Skip-как-ok)**; `SkipHealthy` удалён |
| `resolve_backend_path` | `fn(exe_dir: Option<&Path>, exists: impl Fn(&Path)->bool) -> Option<PathBuf>` | lift `find_backend` с инъекцией fs-probe → детерминируемая None-ветка |
| `next_backoff` | `fn(attempt, failures_in_window, base, max, cap) -> Option<Duration>` | `250ms→500ms→1s→2s→4s`, `None` на attempt 6; **не Some(ZERO)** |
| `ChildHandle` (trait) | `trait ChildHandle { fn alive(&mut self) -> bool; fn kill(&mut self); }` | **абстракция над Child** — pure supervisor НЕ знает `std::process::Child`; тесты дают `FakeChild` (без реального OS-процесса) |
| `reap_tracked` | `fn<H: ChildHandle>(slot: &mut Option<H>) -> bool` | alive() → «tracked==alive»; чистит слот **до** `spawn_decision` (труп не глушит restart) |
| `supervise_step` | `fn<P:HealthProbe, S:BackendSpawner<Handle=H>, H:ChildHandle, C:Clock>(ctx, probe, spawner, clock, emit) -> LoopControl` | тело цикла над инъектируемыми коллабораторами → все A3-поведения unit-drivable фейками |
| traits | `HealthProbe{healthy}` / `BackendSpawner{type Handle: ChildHandle; fn spawn(&mut self)->io::Result<Self::Handle>}` / `Clock{now,sleep}` | развязка от ureq/Command/wall-clock; **`spawn` возвращает `ChildHandle`, не хранит Child внутри pure-кода** |

**Slot-модель:** `Option<H>` = Empty(None)/Running(Some). «Spawning» — транзитно внутри одного шага supervisor (не наблюдаемо). Supervisor **строго один поток** → reservation-против-конкурентного-spawn **не нужен**; единственная гонка = supervisor vs shutdown, закрыта `shutting_down` (проверка до store). `lib.rs` = тонкий адаптер (реальный ureq `HealthProbe` / `Command`-`BackendSpawner` возвращающий обёртку над `Child` : ChildHandle / реальный Clock / AppHandle.emit + mpsc bind-приёмник).

## Unit-тесты (red-first, mutation-noted). **Инвариант: ноль реальных OS-процессов — всё через `FakeChild`/фейки.**
1. `spawn_decision_truth_table` — `(false,false)=Spawn`, `(true,false)=SkipAliveChild`, `(true,true)=SkipAliveChild`, **`(false,true)=ForeignBackend`**. Мут: вернуть Spawn/Skip на `(false,true)` → редён (пиннит: чужой healthy :3005 ≠ ok).
2. `next_backoff_exact_schedule_and_giveup` — `[250,500,1000,2000,4000]ms`, строго неубыв., `None` ровно на attempt 6 (cap 5). Мут: Some(ZERO) / всегда None / off-by-one.
3. `next_state_transition_matrix` — полная {states}×{events}; терминал поглощает; нет `Python*` до `RustReady`. Мут: убрать terminal-absorb / ordering.
4. `next_state_python_ready_idempotent` — два `PythonHealthyOwned` → один переход (single emit). Мут: emit-on-tick → редён.
5. `next_state_rust_bind_err_terminal` — **`RustBindErr` → `Failed`/`Degraded(PortOccupied)`; последующие события НЕ дают RustReady.** Мут: трактовать RustBindErr как RustReady/no-op → редён. ← корр. #1.
6. `next_state_foreign_healthy_not_ready` — **`ForeignHealthy` → `Degraded(ForeignBackend)`, НЕ PythonReady.** Мут: ForeignHealthy→PythonReady → редён. ← корр. #2.
7. `python_ready_requires_owned_health` — `PythonReady` достижим только через `PythonHealthyOwned` (tracked child жив + healthy); `ForeignHealthy` без tracked child не даёт Ready. Мут: снять ownership-условие → редён.
8. `resolve_backend_path_candidate_order` — инъекция exists() → Premium/flat/None. Мут: reorder / убрать None-ветку.
9. `reap_before_decision` — `FakeChild` exited → reap→false→Spawn; alive→true→SkipAliveChild. Мут: пропустить `alive()` reap → zombie-never-restarts редён.
10. `supervise_loop_happy_sequence` — fake probe healthy после N + `FakeSpawner`(FakeChild) + fake clock → emit ровно `[RustReady, PythonStarting, PythonReady]`, `spawn()` ровно 1 раз. Мут: double-spawn/порядок.
11. `supervise_loop_crash_storm_bounded` — FakeChild умирает сразу + вирт-clock 60с → spawn ≤ cap, blip не сбрасывает счётчик, терминал `Degraded(GaveUp)`, без busy-loop. Мут: reset-on-blip / игнор None.
12. `supervise_no_kill_while_alive` — alive+unhealthy >30с вирт-времени → `PythonStarting`, `kill()` НЕ вызван. Мут: readiness kill-deadline → редён (защищает 30–60с OPUS-102).
13. `supervise_foreign_backend_no_spawn` — **stale/foreign :3005: probe.healthy=true, tracked=None → `Degraded(ForeignBackend)`, `spawn()` НЕ вызван, state НЕ PythonReady.** Мут: спавнить/Ready при foreign → редён. ← корр. #2 (stale/foreign тест).
14. `supervise_shutdown_kills_inflight` — `shutting_down` между spawn и store → `FakeChild.kill()` вызван, слот не заполнен. Мут: безусловный store → orphan редён.
15. `get_startup_state_last_write_wins` — `PythonReady` при ZERO слушателях (читает cell, не re-probe). Мут: re-probe :3005 → при fake-down редён.

## UI-тесты (vitest, `ui/`) — приоритет startup-state над onboarding
U1. `degraded_overrides_onboarding_loading` — `onboardingLoading=true` **И** startup=`Degraded` → рендерится **degraded surface**, НЕ сплэш «Джарвис запускается…». Мут: вернуть проверку onboarding перед startup → редён.
U2. `long_python_starting_shows_honest_progress` — startup=`PythonStarting` длительно → прогресс-состояние, **НЕ** ложная ошибка и НЕ терминальный red. Мут: трактовать затяжной старт как failure → редён.
U3. `rust_bind_failure_shows_distinct_error` — startup=`Failed/Degraded(PortOccupied)` → **отдельная понятная ошибка** (порт занят), отличная от not-found/crashed и от model-loading copy. Мут: слить с общим degraded → редён.

## Live-верификации (против dev-machine-masking)
> **Preflight портов (безопасная pre-clean, НЕ `taskkill` по порту):** для :3005/:3006 определить владельца (`Get-NetTCPConnection -LocalPort` → OwningProcess → `Get-Process ... | Select Path`); завершать **только PID, чей executable path подтверждён как KALI** (наш build-путь / `kali-backend.exe`|`kali-desktop.exe`). Чужой процесс на порту → НЕ убивать; тест выполняется как «PORT_OCCUPIED сценарий» (см. ниже), а не затиранием чужого.
> **Cold-boot рычаг:** `KALI_BOOT_DELAY_MS` — **debug-only fake health delay в supervisor/health-probe** (задерживает признание health, НЕ инъектируется в реальный Python/model startup и отсутствует в release-бинаре). Форсирует медленный путь без реальной 30–60с загрузки.

- **first-paint ≤1с**: preflight-clean (выше); fake health delay `KALI_BOOT_DELAY_MS=45000`; 5 запусков; `t0`=верх run(), `t_paint`=первый `get_startup_state` из webview; assert `(t_paint-t0) ≤ 1000ms` при не-Ready backend; p50/max в лог. **Cold обязательно.**
- **30–60с delay не серит окно**: fake health delay 45000; интеракции (drag/click/scroll) все 45с; окно отзывчиво, React показывает **прогрессирующее** `PythonStarting`, НЕ терминальный red и НЕ ложный 5с-failure; затем `PythonReady`.
- **PORT_OCCUPIED (:3006 занят чужим)**: до запуска KALI поднять посторонний listener на :3006; запуск KALI → окно рисуется, состояние **`Failed/Degraded(PORT_OCCUPIED)`**, НИКОГДА RustReady; убрать чужой listener → чистый перезапуск ок.
- **Rust API/WS сразу (Python-independent)**: убрать `kali-backend.exe`; WS `ws://127.0.0.1:3006/ws` + `GET :3006/health`==200 в пределах старта shell; `kernelStage`==0 (нет red на failMs=12000).
- **Degraded/offline честно**: убрать exe → окно рисуется, отдельная degraded-поверхность («backend not found» + log path), НЕ текст загрузки моделей, НЕ голое зелёное, НЕ серое.
- **Второй запуск — без второго backend**: запуск ×2 в пределах 200ms → ровно один `kali-backend` PID, второй invocation **фокусит** окно `main`. Повтор во время cold-start (если single-instance не сработал бы — cross-process `ForeignBackend`-guard не даст второй backend).
- **Crash/restart контролируем**: (a) завершить **подтверждённый по path KALI backend PID** после PythonReady → supervisor respawn **ровно раз**, назад в PythonReady; (b) crash-loop (missing models dir) 30с → spawn ≤ cap, единый settled Degraded без мигания, CPU не пиковый.
- **Shutdown mid-spawn без orphan**: закрыть окно ~200ms (окно spawn) → ноль `kali-backend`, :3005 свободен; закрыть ~1с cold → `stop_backend` <100ms (mutex не держится через IO).
- **get_startup_state отзывчив + late-listener self-heal**: hammer 10ms — каждый <50ms; поздний listener в момент healthy → UI сходится к `PythonReady` за один poll.

## Файлы
- **NEW** `src-tauri/src/startup.rs` — pure leaf (enums, next_state, spawn_decision, resolve_backend_path, next_backoff, reap_tracked, traits, supervise_step) + `#[cfg(test)]`. std-only, ≤800 строк, функции ≤50.
- `src-tauri/src/lib.rs` — `mod startup;`; t0; StartupCell; setup: axum первым (**поток шлёт `RustBindOk`/`RustBindErr` в supervisor через `mpsc`**) → supervisor-поток → shortcut → `Ok(())` (убрать синхронный `start_backend`/`wait_for_backend_ready`); `start_backend`→`BackendSpawner`-адаптер (обёртка `Child`:`ChildHandle`); `get_startup_state` #[command]; **идемпотентный `stop_backend` на `RunEvent::ExitRequested`/`Exit`** (`.build()`+`run(|app,event| …)`), `WindowEvent::Destroyed` — доп. сигнал; invoke_handler += get_startup_state. **(single-instance регистрируется в commit 3, не здесь.)**
- `src-tauri/Cargo.toml` — `tauri-plugin-single-instance = "2"`.
- **NEW** `ui/src/hooks/useStartupState.ts` — mount: `listen('startup://state')` затем `invoke('get_startup_state')` (poll-beats-race) + низкочастотный reconciliation-poll; НЕ трогает `useOnboardingGate.slow`.
- `ui/src/App.tsx` — **читать startup-state ДО onboarding early-return; `Degraded`/`Failed` имеют приоритет над `onboardingLoading`** (сломанный/упавший backend не должен маскироваться сплэшем «Джарвис запускается…»). Рендер degraded/failed поверхности (not-found/crashed/gave-up/port-occupied), отдельно от model-loading copy; первый `get_startup_state` = маркер first-paint.
- `src-tauri/capabilities/*.json` — проверить, что webview может invoke `get_startup_state` (в v2 команды приложения доступны своему webview по умолчанию).

## Commit-слайсы (после утверждения)
1. `feat(desktop): pure startup module + red/green unit tests` — `startup.rs` (enums, next_state, spawn_decision, resolve_backend_path, next_backoff, reap_tracked, `ChildHandle`/HealthProbe/BackendSpawner/Clock traits, supervise_step) + полный `#[cfg(test)]` (15 unit + documented mutation run). **Только `startup.rs` + `mod startup;`(+`#[cfg(test)]`) в lib.rs; НЕ трогает `Cargo.toml`/`Cargo.lock` (ноль новых зависимостей); поведение в lib.rs не вшито.** `cargo test startup::` зелёный. std-only, ort-independent.
2. `fix(desktop): non-blocking boot — return from setup immediately` — переупорядочить lib.rs (axum первым + mpsc bind-сигнал, supervisor-поток, StartupCell, get_startup_state, t0/t_paint, shutting_down, идемпотентный stop на Exit/ExitRequested); убрать синхронный wait. **Чинит серое окно (a,b,c,d,g)** + ownership/PORT_OCCUPIED/FOREIGN.
3. `feat(desktop): single-instance guard` — **ПЕРЕД этим слайсом остановиться:** показать точный `git diff -- src-tauri/Cargo.lock src-tauri/Cargo.toml` и доказать, что пред-существующие чужие dirty-изменения `Cargo.lock` НЕ подхвачены (staging только моих строк: новый `[[package]]` single-instance + его deps). Затем plugin первым (callback фокусит `main`); mutex + ForeignBackend-guard как belt-and-suspenders. (f).
4. `feat(ui): honest boot/degraded surface` — useStartupState + App.tsx (startup-state ДО onboarding early-return, приоритет Degraded/Failed) + U1–U3 vitest; отдельно от model-loading. (e) + граница A3/OPUS-102.

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
4. **Test-delay lever: `KALI_BOOT_DELAY_MS`, только под `debug_assertions`** — **fake health delay в supervisor/health-probe** (задерживает признание health), НЕ инъекция в реальный Python/model startup, отсутствует в release-бинаре. Финализирует live first-paint/30-60с протокол без чистки реального кэша.
5. **Degraded RU-copy** — предложу дефолты при commit 4 (три состояния: «backend не найден» / «backend упал, повтор…» / «не удалось запустить backend»), owner-апрув на месте.
