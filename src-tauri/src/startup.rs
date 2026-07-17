//! Pure, Tauri-/ort-независимое ядро non-blocking boot (OPUS-101 / A3).
//!
//! Нет `std::process::Child`/`ureq`/`AppHandle` — supervision выражен над
//! инъектируемыми трейтами (`ChildHandle`/`HealthProbe`/`BackendSpawner`/`Clock`),
//! поэтому A3-инварианты (spawn-once, ownership, PORT_OCCUPIED, FOREIGN_BACKEND,
//! bounded restart, no-kill-while-alive, reap-before-decision, shutdown-kill)
//! тестируются БЕЗ реальных OS-процессов. `lib.rs` — тонкий адаптер. Несёт только
//! process-liveness, НЕ прогресс загрузки моделей (OPUS-102 = отдельный трек).
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// Машинная причина degraded/failed (UI мапит 1:1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DegradedReason {
    /// Наш :3006 занят чужим/старым процессом (терминально).
    PortOccupied,
    /// :3005 отвечает, но tracked child нет — мы им не владеем.
    ForeignBackend,
    /// `kali-backend.exe` не найден.
    NotFound,
    /// Backend упал; идёт bounded-респавн.
    Crashed,
    /// Исчерпан лимит респавнов (терминально).
    GaveUp,
}

/// Тотальное состояние загрузки desktop-shell.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StartupState {
    ShellReady,
    RustReady,
    PythonStarting,
    PythonReady,
    Degraded(DegradedReason),
    Failed(String),
}

/// Входные события `next_state`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HealthEvent {
    /// axum ЭТОГО процесса успешно забиндил :3006.
    RustBindOk,
    /// bind :3006 не удался (порт занят) — терминально.
    RustBindErr,
    /// `resolve_backend_path` == None.
    ExeMissing,
    /// Tracked child жив И его health успешен (ownership выполнен).
    PythonHealthyOwned,
    /// Tracked child жив, но ещё не healthy.
    PythonUnhealthyAlive,
    /// Tracked child завершился.
    PythonExited,
    /// :3005 healthy, но tracked child нет (чужой backend).
    ForeignHealthy,
    /// Backoff исчерпан — терминально.
    GaveUp,
}

/// Решение о запуске Python-backend (без ambient IO).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SpawnDecision {
    /// Нет живого child и порт свободен — запускаем.
    Spawn,
    /// Наш child жив — не плодим второй.
    SkipAliveChild,
    /// Порт держит чужой процесс — ни spawn, ни Ready.
    ForeignBackend,
}

/// Управление supervision-циклом.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopControl {
    Continue,
    Stop,
}

/// Абстракция над дочерним процессом (реальный — обёртка `std::process::Child`).
pub trait ChildHandle {
    /// Жив ли процесс (реализация делает reap через `try_wait`).
    fn alive(&mut self) -> bool;
    /// Завершить процесс.
    fn kill(&mut self);
}

/// HTTP-health probe Python-backend (:3005).
pub trait HealthProbe {
    fn healthy(&self) -> bool;
}

/// Порождение Python-backend; возвращает `ChildHandle`, не хранит `Child` в pure-коде.
pub trait BackendSpawner {
    type Handle: ChildHandle;
    fn spawn(&mut self) -> std::io::Result<Self::Handle>;
}

/// Источник времени (инъекция для виртуального времени в тестах).
pub trait Clock {
    fn now(&self) -> Instant;
    fn sleep(&self, d: Duration);
}

/// Порядковый ранг для инварианта «RustReady предшествует Python*».
/// Soft-degraded (Foreign/NotFound/Crashed) = 1: Rust уже забиндил, проблема
/// Python-слоя, из неё допустимо восстановление вперёд.
fn rank(s: &StartupState) -> u8 {
    match s {
        StartupState::ShellReady => 0,
        StartupState::RustReady => 1,
        StartupState::PythonStarting => 2,
        StartupState::PythonReady => 3,
        StartupState::Degraded(DegradedReason::PortOccupied)
        | StartupState::Degraded(DegradedReason::GaveUp)
        | StartupState::Failed(_) => 4,
        StartupState::Degraded(_) => 1,
    }
}

/// Терминальные состояния поглощают любые поздние stale-события.
fn is_hard_terminal(s: &StartupState) -> bool {
    matches!(
        s,
        StartupState::Failed(_)
            | StartupState::Degraded(DegradedReason::PortOccupied)
            | StartupState::Degraded(DegradedReason::GaveUp)
    )
}

/// Чистая transition-функция. Терминал поглощает stale; Python*-события не
/// действуют до `RustReady`; `RustBindErr`/`GaveUp` — терминальны.
pub fn next_state(cur: StartupState, ev: HealthEvent) -> StartupState {
    use DegradedReason::*;
    use HealthEvent as E;
    use StartupState as S;
    if is_hard_terminal(&cur) {
        return cur;
    }
    match ev {
        E::RustBindErr => S::Degraded(PortOccupied),
        E::GaveUp => S::Degraded(GaveUp),
        E::RustBindOk if rank(&cur) < rank(&S::RustReady) => S::RustReady,
        E::RustBindOk => cur,
        E::ExeMissing => S::Degraded(NotFound),
        E::ForeignHealthy => S::Degraded(ForeignBackend),
        E::PythonHealthyOwned => guard_python(cur, S::PythonReady),
        E::PythonUnhealthyAlive => guard_python(cur, S::PythonStarting),
        E::PythonExited => guard_python(cur, S::PythonStarting),
    }
}

/// Python*-переход разрешён только если Rust уже забиндил (rank >= RustReady).
fn guard_python(cur: StartupState, target: StartupState) -> StartupState {
    if rank(&cur) >= rank(&StartupState::RustReady) { target } else { cur }
}

/// Truth-table решения о spawn. `(false,true)` = чужой backend (НЕ Spawn/Skip-ok).
pub fn spawn_decision(tracked_alive: bool, healthy: bool) -> SpawnDecision {
    match (tracked_alive, healthy) {
        (true, _) => SpawnDecision::SkipAliveChild,
        (false, false) => SpawnDecision::Spawn,
        (false, true) => SpawnDecision::ForeignBackend,
    }
}

/// Экспоненциальный capped backoff: `attempt`=число падений в окне.
/// `250→500→1000→2000→4000` мс; `None`, если attempt==0 или > cap (give-up).
pub fn next_backoff(attempt: u32, base: Duration, max: Duration, cap: u32) -> Option<Duration> {
    if attempt == 0 || attempt > cap {
        return None;
    }
    let factor = 2u32.saturating_pow(attempt - 1);
    Some((base.saturating_mul(factor)).min(max))
}

/// Число падений в скользящем окне (старые вытесняются по времени).
pub fn failures_in_window(failures: &[Instant], now: Instant, window: Duration) -> u32 {
    failures
        .iter()
        .filter(|t| now.duration_since(**t) <= window)
        .count() as u32
}

/// Кандидаты пути backend в порядке приоритета; инъекция `exists` делает
/// None-ветку (сломанная установка) детерминированной без реального FS.
pub fn resolve_backend_path(exe_dir: Option<&Path>, exists: impl Fn(&Path) -> bool) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(dir) = exe_dir {
        // Premium onedir: kali-backend/kali-backend.exe рядом с kali-desktop.exe.
        candidates.push(dir.join("kali-backend").join("kali-backend.exe"));
        // Lite: плоско рядом.
        candidates.push(dir.join("kali-backend.exe"));
        // Dev: ../../../dist/kali-backend.exe.
        if let Some(root) = dir.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
            candidates.push(root.join("dist").join("kali-backend.exe"));
        }
    }
    // Last-resort: PATH.
    candidates.push(PathBuf::from("kali-backend.exe"));
    candidates.into_iter().find(|p| exists(p))
}

/// Reap: `alive()` → «tracked==alive»; чистит слот ДО решения (труп не глушит restart).
pub fn reap_tracked<H: ChildHandle>(slot: &mut Option<H>) -> bool {
    let alive = slot.as_mut().map_or(false, |c| c.alive());
    if !alive {
        *slot = None;
    }
    alive
}

/// Состояние supervision-цикла (единственный поток → без reservation слота).
pub struct SuperviseCtx<H: ChildHandle> {
    pub state: StartupState,
    pub child: Option<H>,
    pub failures: Vec<Instant>,
    pub backoff_until: Option<Instant>,
    pub shutting_down: bool,
    /// None=bind ещё не резолвлен, Some(true)=ok, Some(false)=порт занят.
    pub rust_bound: Option<bool>,
    pub exe_present: bool,
    pub base: Duration,
    pub max: Duration,
    pub cap: u32,
    pub window: Duration,
}

impl<H: ChildHandle> SuperviseCtx<H> {
    /// Дефолты owner-политики: 250ms→…→4000ms, cap 5, окно 60с.
    pub fn new(exe_present: bool) -> Self {
        SuperviseCtx {
            state: StartupState::ShellReady,
            child: None,
            failures: Vec::new(),
            backoff_until: None,
            shutting_down: false,
            rust_bound: None,
            exe_present,
            base: Duration::from_millis(250),
            max: Duration::from_millis(4000),
            cap: 5,
            window: Duration::from_secs(60),
        }
    }
}

/// Применить событие к состоянию и эмитить ТОЛЬКО при смене (анти-thrash).
fn apply<H: ChildHandle>(
    ctx: &mut SuperviseCtx<H>,
    ev: HealthEvent,
    emit: &mut dyn FnMut(StartupState),
) {
    let new = next_state(ctx.state.clone(), ev);
    if new != ctx.state {
        ctx.state = new.clone();
        emit(new);
    }
}

/// Зарегистрировать падение в окне и решить backoff/give-up.
fn register_failure<H: ChildHandle>(
    ctx: &mut SuperviseCtx<H>,
    now: Instant,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl {
    ctx.failures.push(now);
    ctx.failures.retain(|t| now.duration_since(*t) <= ctx.window);
    let count = failures_in_window(&ctx.failures, now, ctx.window);
    match next_backoff(count, ctx.base, ctx.max, ctx.cap) {
        None => {
            apply(ctx, HealthEvent::GaveUp, emit);
            LoopControl::Stop
        }
        Some(d) => {
            ctx.backoff_until = Some(now + d);
            apply(ctx, HealthEvent::PythonExited, emit);
            LoopControl::Continue
        }
    }
}

/// Один цикл supervision-петли. Держит инвариант: единственный spawner,
/// reap-до-решения, никакого kill живого child, honour shutdown.
pub fn supervise_step<P, S, C>(
    ctx: &mut SuperviseCtx<S::Handle>,
    probe: &P,
    spawner: &mut S,
    clock: &C,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl
where
    P: HealthProbe,
    S: BackendSpawner,
    C: Clock,
{
    if ctx.shutting_down {
        if let Some(mut c) = ctx.child.take() {
            c.kill();
        }
        return LoopControl::Stop;
    }
    if is_hard_terminal(&ctx.state) {
        return LoopControl::Stop;
    }

    // Rust-gate: authoritative bind-сигнал, НЕ polling :3006.
    match ctx.rust_bound {
        None => return LoopControl::Continue,
        Some(false) => {
            apply(ctx, HealthEvent::RustBindErr, emit);
            return LoopControl::Stop;
        }
        Some(true) => {
            if rank(&ctx.state) < rank(&StartupState::RustReady) {
                apply(ctx, HealthEvent::RustBindOk, emit);
                return LoopControl::Continue;
            }
        }
    }

    if !ctx.exe_present {
        apply(ctx, HealthEvent::ExeMissing, emit);
        return LoopControl::Continue;
    }

    // Reap ДО решения: труп не должен подавлять restart.
    let had = ctx.child.is_some();
    let alive = reap_tracked(&mut ctx.child);
    if had && !alive {
        return register_failure(ctx, clock.now(), emit);
    }

    let healthy = probe.healthy();
    match spawn_decision(alive, healthy) {
        SpawnDecision::SkipAliveChild => {
            if healthy {
                apply(ctx, HealthEvent::PythonHealthyOwned, emit); // owned+healthy
            } else {
                apply(ctx, HealthEvent::PythonUnhealthyAlive, emit);
            }
            LoopControl::Continue
        }
        SpawnDecision::ForeignBackend => {
            apply(ctx, HealthEvent::ForeignHealthy, emit);
            LoopControl::Continue
        }
        SpawnDecision::Spawn => spawn_now(ctx, spawner, clock, emit),
    }
}

/// Ветка Spawn: учитывает backoff-окно, honour shutdown после spawn, обрабатывает io-ошибку.
fn spawn_now<S, C>(
    ctx: &mut SuperviseCtx<S::Handle>,
    spawner: &mut S,
    clock: &C,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl
where
    S: BackendSpawner,
    C: Clock,
{
    if let Some(t) = ctx.backoff_until {
        if clock.now() < t {
            return LoopControl::Continue; // ещё в backoff — ждём
        }
    }
    ctx.backoff_until = None;
    match spawner.spawn() {
        Ok(child) => {
            if ctx.shutting_down {
                let mut c = child;
                c.kill(); // shutdown в момент spawn → убить, не сохранять (no orphan)
                return LoopControl::Stop;
            }
            ctx.child = Some(child);
            apply(ctx, HealthEvent::PythonUnhealthyAlive, emit); // только что запущен → Starting
            LoopControl::Continue
        }
        Err(_) => register_failure(ctx, clock.now(), emit),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;
    use std::rc::Rc;

    // ── тест-даблы (ноль реальных OS-процессов) ──────────────────────────────
    struct FakeChild {
        alive_for: Cell<i32>, // >0: жив N вызовов; <0: бесконечно жив; 0: мёртв
        killed: Rc<Cell<bool>>,
    }
    impl ChildHandle for FakeChild {
        fn alive(&mut self) -> bool {
            let n = self.alive_for.get();
            if n < 0 {
                return true;
            }
            if n == 0 {
                return false;
            }
            self.alive_for.set(n - 1);
            true
        }
        fn kill(&mut self) {
            self.killed.set(true);
        }
    }

    struct FakeSpawner {
        count: u32,
        alive_for: i32,
        killed: Rc<Cell<bool>>,
        fail: bool,
    }
    impl BackendSpawner for FakeSpawner {
        type Handle = FakeChild;
        fn spawn(&mut self) -> std::io::Result<FakeChild> {
            self.count += 1;
            if self.fail {
                return Err(std::io::Error::new(std::io::ErrorKind::Other, "spawn-fail"));
            }
            Ok(FakeChild {
                alive_for: Cell::new(self.alive_for),
                killed: self.killed.clone(),
            })
        }
    }

    struct FakeProbe {
        healthy: Rc<Cell<bool>>,
    }
    impl HealthProbe for FakeProbe {
        fn healthy(&self) -> bool {
            self.healthy.get()
        }
    }

    struct FakeClock {
        t: Cell<Instant>,
    }
    impl Clock for FakeClock {
        fn now(&self) -> Instant {
            self.t.get()
        }
        fn sleep(&self, d: Duration) {
            self.t.set(self.t.get() + d);
        }
    }

    fn defaults() -> (Duration, Duration, u32) {
        (Duration::from_millis(250), Duration::from_millis(4000), 5)
    }

    // ── 1. spawn_decision truth-table ────────────────────────────────────────
    #[test]
    fn spawn_decision_truth_table() {
        assert_eq!(spawn_decision(false, false), SpawnDecision::Spawn);
        assert_eq!(spawn_decision(true, false), SpawnDecision::SkipAliveChild);
        assert_eq!(spawn_decision(true, true), SpawnDecision::SkipAliveChild);
        // корр.#2: чужой healthy :3005 → ForeignBackend, НЕ Spawn/Skip-ok
        assert_eq!(spawn_decision(false, true), SpawnDecision::ForeignBackend);
    }

    // ── 2. next_backoff точное расписание + give-up ──────────────────────────
    #[test]
    fn next_backoff_exact_schedule_and_giveup() {
        let (base, max, cap) = defaults();
        let got: Vec<Option<u64>> = (0..=6)
            .map(|a| next_backoff(a, base, max, cap).map(|d| d.as_millis() as u64))
            .collect();
        assert_eq!(
            got,
            vec![None, Some(250), Some(500), Some(1000), Some(2000), Some(4000), None]
        );
    }

    // ── 3. next_state: терминал поглощает; нет Python* до RustReady ───────────
    #[test]
    fn next_state_transition_matrix() {
        // терминал поглощает stale
        let term = StartupState::Degraded(DegradedReason::PortOccupied);
        assert_eq!(next_state(term.clone(), HealthEvent::RustBindOk), term);
        assert_eq!(
            next_state(
                StartupState::Failed("x".into()),
                HealthEvent::PythonHealthyOwned
            ),
            StartupState::Failed("x".into())
        );
        // нет Python* до RustReady
        assert_eq!(
            next_state(StartupState::ShellReady, HealthEvent::PythonHealthyOwned),
            StartupState::ShellReady
        );
        // RustReady предшествует
        assert_eq!(
            next_state(StartupState::ShellReady, HealthEvent::RustBindOk),
            StartupState::RustReady
        );
    }

    // ── 4. PythonReady идемпотентен (эмит на смену) ──────────────────────────
    #[test]
    fn next_state_python_ready_idempotent() {
        let s = next_state(StartupState::RustReady, HealthEvent::PythonHealthyOwned);
        assert_eq!(s, StartupState::PythonReady);
        assert_eq!(
            next_state(s.clone(), HealthEvent::PythonHealthyOwned),
            StartupState::PythonReady
        );
    }

    // ── 5. RustBindErr терминален, никогда RustReady (корр.#1) ────────────────
    #[test]
    fn next_state_rust_bind_err_terminal() {
        let s = next_state(StartupState::ShellReady, HealthEvent::RustBindErr);
        assert_eq!(s, StartupState::Degraded(DegradedReason::PortOccupied));
        // последующие события не дают RustReady
        assert_eq!(next_state(s.clone(), HealthEvent::RustBindOk), s);
    }

    // ── 6. ForeignHealthy → Degraded(ForeignBackend), не Ready (корр.#2) ──────
    #[test]
    fn next_state_foreign_healthy_not_ready() {
        assert_eq!(
            next_state(StartupState::RustReady, HealthEvent::ForeignHealthy),
            StartupState::Degraded(DegradedReason::ForeignBackend)
        );
    }

    // ── 7. PythonReady требует owned health ──────────────────────────────────
    #[test]
    fn python_ready_requires_owned_health() {
        // owned+healthy → Ready
        assert_eq!(
            next_state(StartupState::RustReady, HealthEvent::PythonHealthyOwned),
            StartupState::PythonReady
        );
        // foreign healthy (не owned) → не Ready
        assert_ne!(
            next_state(StartupState::RustReady, HealthEvent::ForeignHealthy),
            StartupState::PythonReady
        );
    }

    // ── 8. resolve_backend_path порядок кандидатов ───────────────────────────
    #[test]
    fn resolve_backend_path_candidate_order() {
        let dir = PathBuf::from("C:/app");
        let premium = dir.join("kali-backend").join("kali-backend.exe");
        let flat = dir.join("kali-backend.exe");
        // только premium существует → premium
        let p = premium.clone();
        assert_eq!(
            resolve_backend_path(Some(&dir), |x| x == p),
            Some(premium.clone())
        );
        // только flat → flat
        let f = flat.clone();
        assert_eq!(resolve_backend_path(Some(&dir), |x| x == f), Some(flat));
        // ничего → None (сломанная установка)
        assert_eq!(resolve_backend_path(Some(&dir), |_| false), None);
    }

    // ── 9. reap до решения ───────────────────────────────────────────────────
    #[test]
    fn reap_before_decision() {
        let killed = Rc::new(Cell::new(false));
        // мёртвый child → reap чистит слот, alive=false
        let mut slot = Some(FakeChild {
            alive_for: Cell::new(0),
            killed: killed.clone(),
        });
        assert!(!reap_tracked(&mut slot));
        assert!(slot.is_none());
        assert_eq!(spawn_decision(false, false), SpawnDecision::Spawn);
        // живой child → alive=true, слот сохранён
        let mut slot2 = Some(FakeChild {
            alive_for: Cell::new(-1),
            killed,
        });
        assert!(reap_tracked(&mut slot2));
        assert!(slot2.is_some());
    }

    fn drive(
        ctx: &mut SuperviseCtx<FakeChild>,
        probe: &FakeProbe,
        spawner: &mut FakeSpawner,
        clock: &FakeClock,
        emits: &mut Vec<StartupState>,
        steps: usize,
    ) -> LoopControl {
        let mut last = LoopControl::Continue;
        for _ in 0..steps {
            last = supervise_step(ctx, probe, spawner, clock, &mut |s| emits.push(s));
            if last == LoopControl::Stop {
                break;
            }
            clock.sleep(Duration::from_millis(500)); // цикл ~500ms
        }
        last
    }

    // ── 10. happy: [RustReady, PythonStarting, PythonReady], spawn ровно раз ──
    #[test]
    fn supervise_loop_happy_sequence() {
        let healthy = Rc::new(Cell::new(false));
        let probe = FakeProbe {
            healthy: healthy.clone(),
        };
        let killed = Rc::new(Cell::new(false));
        let mut spawner = FakeSpawner {
            count: 0,
            alive_for: -1,
            killed,
            fail: false,
        };
        let clock = FakeClock {
            t: Cell::new(Instant::now()),
        };
        let mut ctx = SuperviseCtx::new(true);
        ctx.rust_bound = Some(true);
        let mut emits = Vec::new();
        // 2 шага: RustReady, затем spawn→PythonStarting
        drive(&mut ctx, &probe, &mut spawner, &clock, &mut emits, 2);
        healthy.set(true); // backend стал healthy
        drive(&mut ctx, &probe, &mut spawner, &clock, &mut emits, 2);
        assert_eq!(
            emits,
            vec![
                StartupState::RustReady,
                StartupState::PythonStarting,
                StartupState::PythonReady
            ]
        );
        assert_eq!(spawner.count, 1, "spawn ровно один раз");
    }

    // ── 11. crash-storm bounded → терминальный GaveUp, без storm ──────────────
    #[test]
    fn supervise_loop_crash_storm_bounded() {
        let probe = FakeProbe {
            healthy: Rc::new(Cell::new(false)),
        };
        let killed = Rc::new(Cell::new(false));
        let mut spawner = FakeSpawner {
            count: 0,
            alive_for: 0, // child умирает мгновенно
            killed,
            fail: false,
        };
        let clock = FakeClock {
            t: Cell::new(Instant::now()),
        };
        let mut ctx = SuperviseCtx::new(true);
        ctx.rust_bound = Some(true);
        let mut emits = Vec::new();
        // достаточно шагов + clock.sleep(500) элапсит backoff (макс 4000ms → 8 шагов)
        let ctrl = drive(&mut ctx, &probe, &mut spawner, &clock, &mut emits, 200);
        assert_eq!(ctrl, LoopControl::Stop);
        assert_eq!(ctx.state, StartupState::Degraded(DegradedReason::GaveUp));
        assert!(
            spawner.count <= ctx.cap + 1,
            "спавнов {} > cap+1 {} — restart storm",
            spawner.count,
            ctx.cap + 1
        );
    }

    // ── 12. no kill while alive (защита 30-60с OPUS-102 load) ─────────────────
    #[test]
    fn supervise_no_kill_while_alive() {
        let probe = FakeProbe {
            healthy: Rc::new(Cell::new(false)), // жив, но НЕ healthy
        };
        let killed = Rc::new(Cell::new(false));
        let mut spawner = FakeSpawner {
            count: 0,
            alive_for: -1, // бесконечно жив
            killed: killed.clone(),
            fail: false,
        };
        let clock = FakeClock {
            t: Cell::new(Instant::now()),
        };
        let mut ctx = SuperviseCtx::new(true);
        ctx.rust_bound = Some(true);
        let mut emits = Vec::new();
        drive(&mut ctx, &probe, &mut spawner, &clock, &mut emits, 120); // >30с вирт
        assert_eq!(ctx.state, StartupState::PythonStarting);
        assert!(!killed.get(), "kill() не должен вызываться на живом child");
        assert_eq!(spawner.count, 1);
    }

    // ── 13. foreign backend: не spawn, не Ready (stale/foreign :3005) ─────────
    #[test]
    fn supervise_foreign_backend_no_spawn() {
        let probe = FakeProbe {
            healthy: Rc::new(Cell::new(true)), // :3005 отвечает
        };
        let killed = Rc::new(Cell::new(false));
        let mut spawner = FakeSpawner {
            count: 0,
            alive_for: -1,
            killed,
            fail: false,
        };
        let clock = FakeClock {
            t: Cell::new(Instant::now()),
        };
        let mut ctx = SuperviseCtx::new(true);
        ctx.rust_bound = Some(true);
        let mut emits = Vec::new();
        drive(&mut ctx, &probe, &mut spawner, &clock, &mut emits, 4);
        assert_eq!(
            ctx.state,
            StartupState::Degraded(DegradedReason::ForeignBackend)
        );
        assert_eq!(spawner.count, 0, "чужой backend → НЕ spawn");
        assert_ne!(ctx.state, StartupState::PythonReady);
    }

    // ── 14. shutdown в момент spawn убивает in-flight child (no orphan) ───────
    #[test]
    fn supervise_shutdown_kills_inflight() {
        // shutting_down=true при старте: supervise_step убивает любой child и Stop.
        // Проверяем ветку «shutdown после spawn»: спавним, затем ставим shutdown.
        let probe = FakeProbe {
            healthy: Rc::new(Cell::new(false)),
        };
        let killed = Rc::new(Cell::new(false));
        let mut spawner = FakeSpawner {
            count: 0,
            alive_for: -1,
            killed: killed.clone(),
            fail: false,
        };
        let clock = FakeClock {
            t: Cell::new(Instant::now()),
        };
        let mut ctx = SuperviseCtx::new(true);
        ctx.rust_bound = Some(true);
        let mut emits = Vec::new();
        // шаг1: RustReady; шаг2: spawn → child сохранён
        drive(&mut ctx, &probe, &mut spawner, &clock, &mut emits, 2);
        assert!(ctx.child.is_some());
        // теперь shutdown → следующий шаг убивает tracked child
        ctx.shutting_down = true;
        let ctrl = supervise_step(&mut ctx, &probe, &mut spawner, &clock, &mut |_| {});
        assert_eq!(ctrl, LoopControl::Stop);
        assert!(killed.get(), "tracked child при shutdown должен быть убит");
        assert!(ctx.child.is_none());
    }

    // ── 15. healthy не сбрасывает окно падений (blip не даёт лишних жизней) ────
    #[test]
    fn healthy_step_does_not_reset_failures() {
        let probe = FakeProbe {
            healthy: Rc::new(Cell::new(true)),
        };
        let killed = Rc::new(Cell::new(false));
        let mut spawner = FakeSpawner {
            count: 0,
            alive_for: -1,
            killed,
            fail: false,
        };
        let clock = FakeClock {
            t: Cell::new(Instant::now()),
        };
        let mut ctx = SuperviseCtx::new(true);
        ctx.rust_bound = Some(true);
        ctx.state = StartupState::RustReady;
        // 2 прежних падения в окне
        let now = clock.now();
        ctx.failures = vec![now, now];
        ctx.child = Some(FakeChild {
            alive_for: Cell::new(-1),
            killed: Rc::new(Cell::new(false)),
        });
        let _ = supervise_step(&mut ctx, &probe, &mut spawner, &clock, &mut |_| {});
        assert_eq!(ctx.state, StartupState::PythonReady);
        assert_eq!(ctx.failures.len(), 2, "healthy НЕ должен чистить окно падений");
    }

    // ── failures_in_window вытесняет старые ──────────────────────────────────
    #[test]
    fn failures_in_window_prunes_old() {
        let base = Instant::now();
        let window = Duration::from_secs(60);
        let now = base + Duration::from_secs(120);
        let failures = vec![base, now - Duration::from_secs(30), now];
        // base слишком старый (120с назад) → вне окна; 2 в окне
        assert_eq!(failures_in_window(&failures, now, window), 2);
    }
}
