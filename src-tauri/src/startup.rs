//! Pure, Tauri-/ort-независимое ядро non-blocking boot (OPUS-101 / A3).
//!
//! Нет `std::process::Child`/`ureq`/`AppHandle` — supervision выражен над
//! инъектируемыми трейтами (`ChildHandle`/`HealthProbe`/`BackendSpawner`/`Clock`/
//! `ShutdownSignal`), поэтому A3-инварианты (ownership по instance-ID, spawn-once,
//! PORT_OCCUPIED, FOREIGN_BACKEND, bounded restart, Crashed/SpawnFailed,
//! no-kill-while-alive, reap-fail-closed, shutdown-kill) тестируются БЕЗ реальных
//! OS-процессов. `lib.rs` — тонкий адаптер. Несёт только process-liveness, НЕ
//! прогресс загрузки моделей (OPUS-102 = отдельный трек).
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

/// Машинная причина degraded/failed (UI мапит 1:1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DegradedReason {
    /// Наш :3006 занят чужим/старым процессом (терминально).
    PortOccupied,
    /// :3005 отвечает, но не наш (wrong/missing instance-ID) либо без tracked child.
    ForeignBackend,
    /// `kali-backend.exe` не найден.
    NotFound,
    /// Наш backend упал; идёт bounded-респавн.
    Crashed,
    /// `spawn()` не удался (отдельная причина, не маскируется загрузкой).
    SpawnFailed,
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

/// Типизированный вердикт health-probe (:3005) с проверкой ownership по ID.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProbeStatus {
    /// :3005 не отвечает / не 200.
    Unhealthy,
    /// :3005 healthy И `desktop_instance_id` совпал с ожидаемым (наш backend).
    OwnedHealthy,
    /// :3005 healthy, но ID чужой/отсутствует (не наш).
    ForeignHealthy,
}

/// Решение supervisor над (tracked_alive, ProbeStatus).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    /// Порт свободен, нашего child нет — запускаем.
    Spawn,
    /// Наш child жив, ещё не healthy — ждём (loading).
    Starting,
    /// Наш child жив И owned-healthy — готово.
    Ready,
    /// Порт держит чужой/orphan процесс — ни spawn, ни Ready.
    Foreign,
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
    /// Tracked child жив И owned-healthy (ID совпал).
    PythonHealthyOwned,
    /// Tracked child жив, но ещё не healthy.
    PythonUnhealthyAlive,
    /// :3005 healthy, но не наш (foreign ID) либо без tracked child.
    ForeignHealthy,
    /// Наш backend упал во время работы/backoff.
    Crashed,
    /// `spawn()` вернул io-ошибку.
    SpawnFailed,
    /// `kill()` вернул io-ошибку (отражаем в состоянии).
    KillFailed,
    /// Backoff исчерпан — терминально.
    GaveUp,
}

/// Управление supervision-циклом.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopControl {
    Continue,
    Stop,
}

/// Абстракция над дочерним процессом; io-ошибки видимы (fail-closed).
pub trait ChildHandle {
    /// Жив ли процесс (реализация делает reap через `try_wait`).
    /// `Err` ⇒ вызывающий сохраняет handle и трактует как alive (fail-closed).
    fn try_alive(&mut self) -> io::Result<bool>;
    /// Завершить процесс; `Err` отражается состоянием.
    fn kill(&mut self) -> io::Result<()>;
}

/// HTTP-health probe Python-backend (:3005) с проверкой ownership по instance-ID.
pub trait HealthProbe {
    fn status(&self) -> ProbeStatus;
}

/// Порождение Python-backend; возвращает `ChildHandle`, не хранит `Child` в pure-коде.
pub trait BackendSpawner {
    type Handle: ChildHandle;
    fn spawn(&mut self) -> io::Result<Self::Handle>;
}

/// Источник времени (инъекция для виртуального времени в тестах).
pub trait Clock {
    fn now(&self) -> Instant;
    fn sleep(&self, d: Duration);
}

/// Внешний сигнал завершения (реальный — `AtomicBool`), проверяется вокруг IO.
pub trait ShutdownSignal {
    fn is_set(&self) -> bool;
}

impl ShutdownSignal for AtomicBool {
    fn is_set(&self) -> bool {
        self.load(Ordering::SeqCst)
    }
}

/// Порядковый ранг для инварианта «RustReady предшествует Python*».
/// Soft-degraded (Foreign/NotFound/Crashed/SpawnFailed) = 1: Rust уже забиндил,
/// проблема Python-слоя, из неё допустимо восстановление вперёд.
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
/// действуют до `RustReady`; `RustBindErr`/`GaveUp`/`KillFailed` — терминальны.
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
        E::KillFailed => S::Failed("kill failed".into()),
        E::RustBindOk if rank(&cur) < rank(&S::RustReady) => S::RustReady,
        E::RustBindOk => cur,
        E::ExeMissing => S::Degraded(NotFound),
        E::ForeignHealthy => S::Degraded(ForeignBackend),
        E::PythonHealthyOwned => guard_python(cur, S::PythonReady),
        E::PythonUnhealthyAlive => guard_python(cur, S::PythonStarting),
        E::Crashed => guard_python(cur, S::Degraded(Crashed)),
        E::SpawnFailed => guard_python(cur, S::Degraded(SpawnFailed)),
    }
}

/// Python*-переход разрешён только если Rust уже забиндил (rank >= RustReady).
fn guard_python(cur: StartupState, target: StartupState) -> StartupState {
    if rank(&cur) >= rank(&StartupState::RustReady) {
        target
    } else {
        cur
    }
}

/// Truth-table решения над (tracked_alive, ProbeStatus). `Ready` только при
/// живом tracked child + `OwnedHealthy` (ID совпал). Занятый порт без нашего
/// живого child (в т.ч. чужой ID) → `Foreign` (ни spawn, ни Ready).
pub fn classify(tracked_alive: bool, probe: ProbeStatus) -> Action {
    match (tracked_alive, probe) {
        (true, ProbeStatus::OwnedHealthy) => Action::Ready,
        (true, ProbeStatus::Unhealthy) => Action::Starting,
        (true, ProbeStatus::ForeignHealthy) => Action::Foreign,
        (false, ProbeStatus::Unhealthy) => Action::Spawn,
        (false, _) => Action::Foreign,
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
pub fn resolve_backend_path(
    exe_dir: Option<&Path>,
    exists: impl Fn(&Path) -> bool,
) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(dir) = exe_dir {
        candidates.push(dir.join("kali-backend").join("kali-backend.exe"));
        candidates.push(dir.join("kali-backend.exe"));
        if let Some(root) = dir
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
        {
            candidates.push(root.join("dist").join("kali-backend.exe"));
        }
    }
    candidates.push(PathBuf::from("kali-backend.exe"));
    candidates.into_iter().find(|p| exists(p))
}

/// Reap: `try_alive()` → «tracked==alive»; чистит слот ДО решения. **Fail-closed:**
/// io-ошибка `try_alive` ⇒ handle сохраняется и трактуется как alive (никогда не
/// приведёт к spawn второго backend).
pub fn reap_tracked<H: ChildHandle>(slot: &mut Option<H>) -> bool {
    match slot.as_mut() {
        None => false,
        Some(c) => match c.try_alive() {
            Ok(true) => true,
            Ok(false) => {
                *slot = None;
                false
            }
            Err(_) => true,
        },
    }
}

/// Состояние supervision-цикла (единственный поток → без reservation слота).
pub struct SuperviseCtx<H: ChildHandle> {
    pub state: StartupState,
    pub child: Option<H>,
    pub failures: Vec<Instant>,
    pub backoff_until: Option<Instant>,
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

/// Убить tracked child (при shutdown); io-ошибку kill отразить как `Failed`. Stop.
fn stop_kill<H: ChildHandle>(
    ctx: &mut SuperviseCtx<H>,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl {
    if let Some(mut c) = ctx.child.take() {
        if c.kill().is_err() {
            apply(ctx, HealthEvent::KillFailed, emit);
        }
    }
    LoopControl::Stop
}

/// Зарегистрировать падение (crash/spawn-fail) в окне и решить backoff/give-up.
fn register_failure<H: ChildHandle>(
    ctx: &mut SuperviseCtx<H>,
    now: Instant,
    cause: HealthEvent,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl {
    ctx.failures.push(now);
    ctx.failures
        .retain(|t| now.duration_since(*t) <= ctx.window);
    let count = failures_in_window(&ctx.failures, now, ctx.window);
    match next_backoff(count, ctx.base, ctx.max, ctx.cap) {
        None => {
            apply(ctx, HealthEvent::GaveUp, emit);
            LoopControl::Stop
        }
        Some(d) => {
            ctx.backoff_until = Some(now + d);
            apply(ctx, cause, emit);
            LoopControl::Continue
        }
    }
}

/// Один цикл supervision-петли. Инварианты: единственный spawner, reap-до-решения
/// (fail-closed), никакого kill живого child, shutdown вокруг probe/spawn.
pub fn supervise_step<P, S, C>(
    ctx: &mut SuperviseCtx<S::Handle>,
    probe: &P,
    spawner: &mut S,
    clock: &C,
    shutdown: &dyn ShutdownSignal,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl
where
    P: HealthProbe,
    S: BackendSpawner,
    C: Clock,
{
    if shutdown.is_set() {
        return stop_kill(ctx, emit);
    }
    if is_hard_terminal(&ctx.state) {
        return LoopControl::Stop;
    }

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

    let had = ctx.child.is_some();
    let alive = reap_tracked(&mut ctx.child);
    if had && !alive {
        return register_failure(ctx, clock.now(), HealthEvent::Crashed, emit);
    }

    let status = probe.status();
    if shutdown.is_set() {
        return stop_kill(ctx, emit);
    }
    match classify(alive, status) {
        Action::Ready => apply(ctx, HealthEvent::PythonHealthyOwned, emit),
        Action::Starting => apply(ctx, HealthEvent::PythonUnhealthyAlive, emit),
        Action::Foreign => apply(ctx, HealthEvent::ForeignHealthy, emit),
        Action::Spawn => return spawn_now(ctx, spawner, clock, shutdown, emit),
    }
    LoopControl::Continue
}

/// Ветка Spawn: backoff-окно, shutdown до и после spawn (kill in-flight → no orphan),
/// io-ошибка spawn → distinct `SpawnFailed`.
fn spawn_now<S, C>(
    ctx: &mut SuperviseCtx<S::Handle>,
    spawner: &mut S,
    clock: &C,
    shutdown: &dyn ShutdownSignal,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl
where
    S: BackendSpawner,
    C: Clock,
{
    if let Some(t) = ctx.backoff_until {
        if clock.now() < t {
            return LoopControl::Continue;
        }
    }
    ctx.backoff_until = None;
    if shutdown.is_set() {
        return LoopControl::Stop;
    }
    match spawner.spawn() {
        Ok(mut child) => {
            if shutdown.is_set() {
                if child.kill().is_err() {
                    apply(ctx, HealthEvent::KillFailed, emit);
                }
                return LoopControl::Stop;
            }
            ctx.child = Some(child);
            apply(ctx, HealthEvent::PythonUnhealthyAlive, emit);
            LoopControl::Continue
        }
        Err(_) => register_failure(ctx, clock.now(), HealthEvent::SpawnFailed, emit),
    }
}

#[cfg(test)]
mod tests;
