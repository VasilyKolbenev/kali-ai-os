//! Pure, Tauri-/ort-независимое ядро non-blocking boot (OPUS-101 / A3).
//!
//! Нет `std::process::Child`/`ureq`/`AppHandle` — supervision выражен над
//! инъектируемыми трейтами (`ChildHandle`/`HealthProbe`/`BackendSpawner`/`Clock`/
//! `ShutdownSignal`), поэтому A3-инварианты (ownership по instance-ID, typed
//! liveness, PORT_OCCUPIED, FOREIGN_BACKEND, bounded restart, Crashed/SpawnFailed,
//! terminate-retry, reap-fail-closed) тестируются БЕЗ реальных OS-процессов.
//! `lib.rs` — тонкий адаптер. Несёт только process-liveness, НЕ прогресс загрузки
//! моделей (OPUS-102 = отдельный трек).
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
    /// Статус процесса неизвестен (`try_alive` вернул io-ошибку) — восстановимо.
    ProcessStatusUnknown,
    /// Rust axum не смог стартовать (init/bind error ≠ AddrInUse, или channel
    /// disconnect) — терминально, НЕ «порт занят».
    RustStartupFailed,
    /// Исчерпан лимит респавнов (терминально).
    GaveUp,
}

/// Результат bind Rust axum (:3006), приходящий authoritative-каналом.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BindOutcome {
    /// Успешный bind нашего процесса.
    Ok,
    /// `AddrInUse` — порт держит чужой/старый процесс.
    PortOccupied,
    /// Другая init/bind-ошибка или channel disconnect (не «порт занят»).
    StartupFailed,
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

/// Типизированная живость tracked-процесса.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Liveness {
    /// Нет tracked child.
    Absent,
    /// Tracked child жив.
    Alive,
    /// `try_alive` вернул io-ошибку — статус неизвестен, handle сохранён.
    Unknown,
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

/// Решение supervisor над (Liveness, ProbeStatus).
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
    /// Статус процесса неизвестен — ни spawn, ни Ready (fail-closed).
    Unknown,
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
    /// `try_alive` вернул io-ошибку (liveness Unknown).
    ProcessUnknown,
    /// Наш backend упал во время работы/backoff.
    Crashed,
    /// `spawn()` вернул io-ошибку.
    SpawnFailed,
    /// `terminate_and_wait()` вернул io-ошибку (отражаем в состоянии).
    KillFailed,
    /// Rust axum не смог стартовать (не AddrInUse) — терминально.
    RustStartupFailed,
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
    /// `Err` ⇒ вызывающий сохраняет handle и трактует как `Unknown`.
    fn try_alive(&mut self) -> io::Result<bool>;
    /// Убить процесс И дождаться его (`wait` — часть успешной termination).
    /// `Err` ⇒ handle НЕ теряется, termination повторяется на следующем шаге.
    fn terminate_and_wait(&mut self) -> io::Result<()>;
}

/// Порождённый backend вместе с его per-spawn instance-ID (ownership-контракт).
pub struct Spawned<H> {
    pub handle: H,
    pub instance_id: String,
}

/// HTTP-health probe Python-backend (:3005). Сравнивает `desktop_instance_id`
/// из `/health` с ожидаемым ID нашего tracked child (ownership по ID).
pub trait HealthProbe {
    fn status(&self, expected_instance_id: Option<&str>) -> ProbeStatus;
}

/// Порождение Python-backend; возвращает `Spawned` (handle + свежий instance-ID).
pub trait BackendSpawner {
    type Handle: ChildHandle;
    fn spawn(&mut self) -> io::Result<Spawned<Self::Handle>>;
}

/// Источник времени (инъекция для виртуального времени в тестах).
pub trait Clock {
    fn now(&self) -> Instant;
}

/// Внешний сигнал завершения (реальный — `AtomicBool`), проверяется вокруг IO.
pub trait ShutdownSignal {
    fn is_set(&self) -> bool;
}

// ── debug-only тест-рычаг `KALI_BOOT_DELAY_MS` ───────────────────────────────
// Позволяет вручную проверить неблокирующий boot: искусственно откладывает
// признание готовности backend. Весь блок (включая саму строку имени
// переменной) компилируется ТОЛЬКО при `debug_assertions` и отсутствует в
// release-сборке.

/// Верхняя граница искусственной задержки — защита от опечатки (10 минут).
#[cfg(debug_assertions)]
pub const MAX_BOOT_DELAY_MS: u64 = 600_000;

/// Разобрать значение `KALI_BOOT_DELAY_MS`.
///
/// Любое некорректное значение (отсутствует, пустое, не число, отрицательное,
/// переполнение u64) → `0` = рычаг выключен (fail-safe, без паники). Слишком
/// большое зажимается в [`MAX_BOOT_DELAY_MS`].
///
/// Args:
///     raw: Сырое значение переменной окружения, если она задана.
///
/// Returns:
///     Задержка в миллисекундах, `0` = выключено.
#[cfg(debug_assertions)]
pub fn parse_boot_delay_ms(raw: Option<&str>) -> u64 {
    raw.and_then(|s| s.trim().parse::<u64>().ok())
        .unwrap_or(0)
        .min(MAX_BOOT_DELAY_MS)
}

/// Отложить признание ТОЛЬКО `OwnedHealthy` до истечения `delay`.
///
/// До дедлайна возвращается `Unhealthy`, из-за чего supervisor держит
/// `PythonStarting` и НЕ убивает живой процесс (`Alive` + `Unhealthy` →
/// `Action::Starting`, не `Spawn`). `ForeignHealthy` и реальная неготовность
/// не маскируются — рычаг не должен прятать настоящие проблемы.
#[cfg(debug_assertions)]
pub fn gate_owned_healthy(probe: ProbeStatus, elapsed: Duration, delay: Duration) -> ProbeStatus {
    if probe == ProbeStatus::OwnedHealthy && elapsed < delay {
        ProbeStatus::Unhealthy
    } else {
        probe
    }
}

/// Debug-обёртка над реальным probe: неблокирующая проверка дедлайна (без sleep).
#[cfg(debug_assertions)]
pub struct DelayedProbe<'a, P, C> {
    inner: P,
    clock: &'a C,
    t0: Instant,
    delay: Duration,
}

#[cfg(debug_assertions)]
impl<'a, P, C> DelayedProbe<'a, P, C> {
    /// Создать обёртку; `delay_ms` = 0 делает её прозрачной.
    pub fn new(inner: P, clock: &'a C, t0: Instant, delay_ms: u64) -> Self {
        DelayedProbe {
            inner,
            clock,
            t0,
            delay: Duration::from_millis(delay_ms),
        }
    }

    /// Доступ к обёрнутому probe — существует исключительно для тестов.
    #[cfg(test)]
    pub fn inner_ref(&self) -> &P {
        &self.inner
    }
}

#[cfg(debug_assertions)]
impl<P: HealthProbe, C: Clock> HealthProbe for DelayedProbe<'_, P, C> {
    fn status(&self, expected_instance_id: Option<&str>) -> ProbeStatus {
        // saturating: часы не обязаны быть монотонными относительно t0.
        let elapsed = self.clock.now().saturating_duration_since(self.t0);
        gate_owned_healthy(self.inner.status(expected_instance_id), elapsed, self.delay)
    }
}

impl ShutdownSignal for AtomicBool {
    fn is_set(&self) -> bool {
        self.load(Ordering::SeqCst)
    }
}

/// Порядковый ранг для инварианта «RustReady предшествует Python*».
/// Soft-degraded (Foreign/NotFound/Crashed/SpawnFailed/ProcessStatusUnknown) = 1:
/// Rust уже забиндил, проблема Python-слоя, восстановление вперёд допустимо.
fn rank(s: &StartupState) -> u8 {
    match s {
        StartupState::ShellReady => 0,
        StartupState::RustReady => 1,
        StartupState::PythonStarting => 2,
        StartupState::PythonReady => 3,
        StartupState::Degraded(DegradedReason::PortOccupied)
        | StartupState::Degraded(DegradedReason::RustStartupFailed)
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
            | StartupState::Degraded(DegradedReason::RustStartupFailed)
            | StartupState::Degraded(DegradedReason::GaveUp)
    )
}

/// Переход разрешён только после `RustReady` (Rust-gate). До него — no-op.
fn guard_after_rust(cur: StartupState, target: StartupState) -> StartupState {
    if rank(&cur) >= rank(&StartupState::RustReady) {
        target
    } else {
        cur
    }
}

/// Чистая transition-функция. Терминал поглощает stale; Python/Degraded-события
/// не действуют до `RustReady`; `RustBindErr`/`GaveUp`/`KillFailed` — терминальны.
pub fn next_state(cur: StartupState, ev: HealthEvent) -> StartupState {
    use DegradedReason::*;
    use HealthEvent as E;
    use StartupState as S;
    if is_hard_terminal(&cur) {
        return cur;
    }
    match ev {
        E::RustBindErr => S::Degraded(PortOccupied),
        E::RustStartupFailed => S::Degraded(RustStartupFailed),
        E::GaveUp => S::Degraded(GaveUp),
        E::KillFailed => S::Failed("kill failed".into()),
        E::RustBindOk if rank(&cur) < rank(&S::RustReady) => S::RustReady,
        E::RustBindOk => cur,
        E::ExeMissing => guard_after_rust(cur, S::Degraded(NotFound)),
        E::ForeignHealthy => guard_after_rust(cur, S::Degraded(ForeignBackend)),
        E::ProcessUnknown => guard_after_rust(cur, S::Degraded(ProcessStatusUnknown)),
        E::PythonHealthyOwned => guard_after_rust(cur, S::PythonReady),
        E::PythonUnhealthyAlive => guard_after_rust(cur, S::PythonStarting),
        E::Crashed => guard_after_rust(cur, S::Degraded(Crashed)),
        E::SpawnFailed => guard_after_rust(cur, S::Degraded(SpawnFailed)),
    }
}

/// Truth-table над (Liveness, ProbeStatus). `Ready` только при `Alive` +
/// `OwnedHealthy` (ID совпал). `Unknown` liveness → `Unknown` (ни Ready, ни Spawn).
/// Занятый порт без нашего живого child (в т.ч. чужой ID) → `Foreign`.
pub fn classify(liveness: Liveness, probe: ProbeStatus) -> Action {
    use Liveness as L;
    use ProbeStatus as P;
    match (liveness, probe) {
        (L::Unknown, _) => Action::Unknown,
        (L::Alive, P::OwnedHealthy) => Action::Ready,
        (L::Alive, P::Unhealthy) => Action::Starting,
        (L::Alive, P::ForeignHealthy) => Action::Foreign,
        (L::Absent, P::Unhealthy) => Action::Spawn,
        (L::Absent, _) => Action::Foreign,
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

/// Reap tracked-процесса → `Liveness`. Подтверждённый exit (`Ok(false)`) чистит
/// слот (handle+ID). `Err` → `Unknown`, слот СОХРАНЯЕТСЯ (fail-closed).
pub fn reap_tracked<H: ChildHandle>(slot: &mut Option<Spawned<H>>) -> Liveness {
    match slot.as_mut() {
        None => Liveness::Absent,
        Some(sp) => match sp.handle.try_alive() {
            Ok(true) => Liveness::Alive,
            Ok(false) => {
                *slot = None;
                Liveness::Absent
            }
            Err(_) => Liveness::Unknown,
        },
    }
}

/// Состояние supervision-цикла (единственный поток → без reservation слота).
pub struct SuperviseCtx<H: ChildHandle> {
    pub state: StartupState,
    pub tracked: Option<Spawned<H>>,
    pub failures: Vec<Instant>,
    pub backoff_until: Option<Instant>,
    /// None=bind ещё не резолвлен; иначе authoritative-результат bind :3006.
    pub rust_bound: Option<BindOutcome>,
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
            tracked: None,
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

    fn expected_id(&self) -> Option<&str> {
        self.tracked.as_ref().map(|s| s.instance_id.as_str())
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

/// Terminate tracked child (при shutdown). Успех (kill+wait) чистит слот и Stop;
/// ошибка сохраняет handle+ID, отражает `KillFailed` и Continue (retry на след. шаге).
fn stop_terminate<H: ChildHandle>(
    ctx: &mut SuperviseCtx<H>,
    emit: &mut dyn FnMut(StartupState),
) -> LoopControl {
    match ctx.tracked.as_mut() {
        None => LoopControl::Stop,
        Some(sp) => match sp.handle.terminate_and_wait() {
            Ok(()) => {
                ctx.tracked = None;
                LoopControl::Stop
            }
            Err(_) => {
                apply(ctx, HealthEvent::KillFailed, emit);
                LoopControl::Continue
            }
        },
    }
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
/// (fail-closed + typed liveness), ownership по instance-ID, shutdown вокруг
/// probe/spawn с terminate-retry.
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
        return stop_terminate(ctx, emit);
    }
    if is_hard_terminal(&ctx.state) {
        return LoopControl::Stop;
    }

    match ctx.rust_bound {
        None => return LoopControl::Continue,
        Some(BindOutcome::PortOccupied) => {
            apply(ctx, HealthEvent::RustBindErr, emit);
            return LoopControl::Stop;
        }
        Some(BindOutcome::StartupFailed) => {
            apply(ctx, HealthEvent::RustStartupFailed, emit);
            return LoopControl::Stop;
        }
        Some(BindOutcome::Ok) => {
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

    let had = ctx.tracked.is_some();
    let liveness = reap_tracked(&mut ctx.tracked);
    if had && liveness == Liveness::Absent {
        return register_failure(ctx, clock.now(), HealthEvent::Crashed, emit);
    }

    let status = probe.status(ctx.expected_id());
    if shutdown.is_set() {
        return stop_terminate(ctx, emit);
    }
    match classify(liveness, status) {
        Action::Ready => apply(ctx, HealthEvent::PythonHealthyOwned, emit),
        Action::Starting => apply(ctx, HealthEvent::PythonUnhealthyAlive, emit),
        Action::Foreign => apply(ctx, HealthEvent::ForeignHealthy, emit),
        Action::Unknown => apply(ctx, HealthEvent::ProcessUnknown, emit),
        Action::Spawn => return spawn_now(ctx, spawner, clock, shutdown, emit),
    }
    LoopControl::Continue
}

/// Ветка Spawn: backoff-окно, shutdown до и после spawn. При shutdown после spawn
/// — terminate; ошибка termination сохраняет child (store) для retry, не orphan.
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
        Ok(mut spawned) => {
            if shutdown.is_set() {
                return match spawned.handle.terminate_and_wait() {
                    Ok(()) => LoopControl::Stop,
                    Err(_) => {
                        apply(ctx, HealthEvent::KillFailed, emit);
                        ctx.tracked = Some(spawned); // сохранить для retry (no orphan)
                        LoopControl::Continue
                    }
                };
            }
            ctx.tracked = Some(spawned);
            apply(ctx, HealthEvent::PythonUnhealthyAlive, emit);
            LoopControl::Continue
        }
        Err(_) => register_failure(ctx, clock.now(), HealthEvent::SpawnFailed, emit),
    }
}

#[cfg(test)]
mod tests;
