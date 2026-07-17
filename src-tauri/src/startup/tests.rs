//! Unit-тесты pure startup-ядра. Ноль реальных OS-процессов — всё через фейки.
use super::*;
use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

// ── тест-даблы ───────────────────────────────────────────────────────────────
struct FakeChild {
    alive_for: Cell<i32>,           // <0 бесконечно; 0 мёртв; >0 жив N вызовов
    try_err: bool,                  // try_alive → Err (liveness Unknown)
    terminate_err_times: Cell<i32>, // сколько раз terminate вернёт Err перед Ok
    terminated: Rc<Cell<bool>>,
    waited: Rc<Cell<bool>>,
}

impl FakeChild {
    fn new(alive_for: i32) -> Self {
        FakeChild {
            alive_for: Cell::new(alive_for),
            try_err: false,
            terminate_err_times: Cell::new(0),
            terminated: Rc::new(Cell::new(false)),
            waited: Rc::new(Cell::new(false)),
        }
    }
}

impl ChildHandle for FakeChild {
    fn try_alive(&mut self) -> std::io::Result<bool> {
        if self.try_err {
            return Err(std::io::Error::new(std::io::ErrorKind::Other, "try_wait"));
        }
        let n = self.alive_for.get();
        if n < 0 {
            return Ok(true);
        }
        if n == 0 {
            return Ok(false);
        }
        self.alive_for.set(n - 1);
        Ok(true)
    }
    fn terminate_and_wait(&mut self) -> std::io::Result<()> {
        let n = self.terminate_err_times.get();
        if n > 0 {
            self.terminate_err_times.set(n - 1);
            return Err(std::io::Error::new(std::io::ErrorKind::Other, "terminate"));
        }
        self.terminated.set(true);
        self.waited.set(true); // wait — часть успешной termination
        Ok(())
    }
}

fn spawned(id: &str, child: FakeChild) -> Spawned<FakeChild> {
    Spawned {
        handle: child,
        instance_id: id.to_string(),
    }
}

struct FakeSpawner {
    count: u32,
    alive_for: i32,
    fail: bool,
    terminate_err_times: i32,
    set_shutdown_on_spawn: Option<Arc<AtomicBool>>,
    last_terminated: Rc<Cell<bool>>,
    last_waited: Rc<Cell<bool>>,
}

impl FakeSpawner {
    fn new(alive_for: i32) -> Self {
        FakeSpawner {
            count: 0,
            alive_for,
            fail: false,
            terminate_err_times: 0,
            set_shutdown_on_spawn: None,
            last_terminated: Rc::new(Cell::new(false)),
            last_waited: Rc::new(Cell::new(false)),
        }
    }
}

impl BackendSpawner for FakeSpawner {
    type Handle = FakeChild;
    fn spawn(&mut self) -> std::io::Result<Spawned<FakeChild>> {
        self.count += 1;
        if let Some(sd) = &self.set_shutdown_on_spawn {
            sd.store(true, Ordering::SeqCst); // shutdown выставлен ВНУТРИ spawn
        }
        if self.fail {
            return Err(std::io::Error::new(std::io::ErrorKind::Other, "spawn-fail"));
        }
        let terminated = Rc::new(Cell::new(false));
        let waited = Rc::new(Cell::new(false));
        self.last_terminated = terminated.clone();
        self.last_waited = waited.clone();
        let child = FakeChild {
            alive_for: Cell::new(self.alive_for),
            try_err: false,
            terminate_err_times: Cell::new(self.terminate_err_times),
            terminated,
            waited,
        };
        Ok(spawned(&format!("id-{}", self.count), child))
    }
}

struct FakeProbe {
    up: Cell<bool>,
    serving_id: RefCell<Option<String>>,
}
impl FakeProbe {
    fn new(up: bool, serving: Option<&str>) -> Self {
        FakeProbe {
            up: Cell::new(up),
            serving_id: RefCell::new(serving.map(|s| s.to_string())),
        }
    }
}
impl HealthProbe for FakeProbe {
    fn status(&self, expected: Option<&str>) -> ProbeStatus {
        if !self.up.get() {
            return ProbeStatus::Unhealthy;
        }
        match (expected, self.serving_id.borrow().as_deref()) {
            (Some(e), Some(s)) if e == s => ProbeStatus::OwnedHealthy,
            _ => ProbeStatus::ForeignHealthy,
        }
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
fn clock() -> FakeClock {
    FakeClock {
        t: Cell::new(Instant::now()),
    }
}

fn ready_ctx() -> SuperviseCtx<FakeChild> {
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    ctx.state = StartupState::RustReady;
    ctx
}

fn drive(
    ctx: &mut SuperviseCtx<FakeChild>,
    probe: &FakeProbe,
    spawner: &mut FakeSpawner,
    clock: &FakeClock,
    emits: &mut Vec<StartupState>,
    steps: usize,
) -> LoopControl {
    let never = AtomicBool::new(false);
    let mut last = LoopControl::Continue;
    for _ in 0..steps {
        last = supervise_step(ctx, probe, spawner, clock, &never, &mut |s| emits.push(s));
        if last == LoopControl::Stop {
            break;
        }
        clock.sleep(Duration::from_millis(500));
    }
    last
}

fn all_states() -> Vec<StartupState> {
    use DegradedReason::*;
    vec![
        StartupState::ShellReady,
        StartupState::RustReady,
        StartupState::PythonStarting,
        StartupState::PythonReady,
        StartupState::Degraded(PortOccupied),
        StartupState::Degraded(ForeignBackend),
        StartupState::Degraded(NotFound),
        StartupState::Degraded(Crashed),
        StartupState::Degraded(SpawnFailed),
        StartupState::Degraded(ProcessStatusUnknown),
        StartupState::Degraded(GaveUp),
        StartupState::Failed("x".into()),
    ]
}

fn all_events() -> Vec<HealthEvent> {
    use HealthEvent::*;
    vec![
        RustBindOk,
        RustBindErr,
        ExeMissing,
        PythonHealthyOwned,
        PythonUnhealthyAlive,
        ForeignHealthy,
        ProcessUnknown,
        Crashed,
        SpawnFailed,
        KillFailed,
        GaveUp,
    ]
}

fn is_terminal(s: &StartupState) -> bool {
    matches!(
        s,
        StartupState::Failed(_)
            | StartupState::Degraded(DegradedReason::PortOccupied)
            | StartupState::Degraded(DegradedReason::GaveUp)
    )
}

// ── 1. classify truth-table (typed liveness + ownership) ─────────────────────
#[test]
fn classify_truth_table() {
    use Liveness::*;
    use ProbeStatus::*;
    assert_eq!(classify(Alive, OwnedHealthy), Action::Ready);
    assert_eq!(classify(Alive, Unhealthy), Action::Starting);
    assert_eq!(classify(Alive, ForeignHealthy), Action::Foreign);
    assert_eq!(classify(Absent, Unhealthy), Action::Spawn);
    assert_eq!(classify(Absent, OwnedHealthy), Action::Foreign);
    assert_eq!(classify(Absent, ForeignHealthy), Action::Foreign);
    // Unknown НИКОГДА не Ready/Spawn, даже при OwnedHealthy
    assert_eq!(classify(Unknown, OwnedHealthy), Action::Unknown);
    assert_eq!(classify(Unknown, Unhealthy), Action::Unknown);
}

// ── 2. next_backoff расписание + give-up ─────────────────────────────────────
#[test]
fn next_backoff_exact_schedule_and_giveup() {
    let (base, max, cap) = (Duration::from_millis(250), Duration::from_millis(4000), 5);
    let got: Vec<Option<u64>> = (0..=6)
        .map(|a| next_backoff(a, base, max, cap).map(|d| d.as_millis() as u64))
        .collect();
    assert_eq!(
        got,
        vec![
            None,
            Some(250),
            Some(500),
            Some(1000),
            Some(2000),
            Some(4000),
            None
        ]
    );
}

// ── 3. matrix_invariants: total + структурные инварианты по всем переходам ────
#[test]
fn next_state_matrix_invariants() {
    for s in all_states() {
        for ev in all_events() {
            let out = next_state(s.clone(), ev.clone());
            if is_terminal(&s) {
                assert_eq!(out, s, "терминал {s:?} должен поглощать {ev:?}");
            }
            if s == StartupState::ShellReady {
                // до RustReady только Rust-события/терминалы меняют состояние
                let allowed = matches!(
                    ev,
                    HealthEvent::RustBindOk
                        | HealthEvent::RustBindErr
                        | HealthEvent::GaveUp
                        | HealthEvent::KillFailed
                );
                if !allowed {
                    assert_eq!(out, StartupState::ShellReady, "Rust-gate обойдён: {ev:?}");
                }
            }
        }
    }
}

// ── 3b. explicit expected для каждого события из ключевых состояний ───────────
#[test]
fn next_state_explicit_transitions() {
    use DegradedReason as D;
    use HealthEvent as E;
    use StartupState as S;
    // из RustReady — все 11 событий
    let rr = S::RustReady;
    assert_eq!(next_state(rr.clone(), E::RustBindOk), S::RustReady);
    assert_eq!(
        next_state(rr.clone(), E::RustBindErr),
        S::Degraded(D::PortOccupied)
    );
    assert_eq!(
        next_state(rr.clone(), E::ExeMissing),
        S::Degraded(D::NotFound)
    );
    assert_eq!(
        next_state(rr.clone(), E::PythonHealthyOwned),
        S::PythonReady
    );
    assert_eq!(
        next_state(rr.clone(), E::PythonUnhealthyAlive),
        S::PythonStarting
    );
    assert_eq!(
        next_state(rr.clone(), E::ForeignHealthy),
        S::Degraded(D::ForeignBackend)
    );
    assert_eq!(
        next_state(rr.clone(), E::ProcessUnknown),
        S::Degraded(D::ProcessStatusUnknown)
    );
    assert_eq!(next_state(rr.clone(), E::Crashed), S::Degraded(D::Crashed));
    assert_eq!(
        next_state(rr.clone(), E::SpawnFailed),
        S::Degraded(D::SpawnFailed)
    );
    assert!(matches!(
        next_state(rr.clone(), E::KillFailed),
        S::Failed(_)
    ));
    assert_eq!(next_state(rr, E::GaveUp), S::Degraded(D::GaveUp));
    // Rust-gate: ExeMissing/ForeignHealthy/ProcessUnknown до RustReady — no-op
    assert_eq!(next_state(S::ShellReady, E::ExeMissing), S::ShellReady);
    assert_eq!(next_state(S::ShellReady, E::ForeignHealthy), S::ShellReady);
    assert_eq!(next_state(S::ShellReady, E::ProcessUnknown), S::ShellReady);
    // восстановление из soft-degraded (rank 1) вперёд
    assert_eq!(
        next_state(S::Degraded(D::ProcessStatusUnknown), E::PythonHealthyOwned),
        S::PythonReady
    );
    assert_eq!(
        next_state(S::Degraded(D::Crashed), E::PythonUnhealthyAlive),
        S::PythonStarting
    );
}

// ── 4. resolve_backend_path порядок ──────────────────────────────────────────
#[test]
fn resolve_backend_path_candidate_order() {
    let dir = PathBuf::from("C:/app");
    let premium = dir.join("kali-backend").join("kali-backend.exe");
    let flat = dir.join("kali-backend.exe");
    let p = premium.clone();
    assert_eq!(resolve_backend_path(Some(&dir), |x| x == p), Some(premium));
    let f = flat.clone();
    assert_eq!(resolve_backend_path(Some(&dir), |x| x == f), Some(flat));
    assert_eq!(resolve_backend_path(Some(&dir), |_| false), None);
}

// ── 5. reap: Absent/Alive/Unknown ────────────────────────────────────────────
#[test]
fn reap_typed_liveness() {
    let mut dead = Some(spawned("id-1", FakeChild::new(0)));
    assert_eq!(reap_tracked(&mut dead), Liveness::Absent);
    assert!(dead.is_none(), "подтверждённый exit чистит слот");
    let mut alive = Some(spawned("id-1", FakeChild::new(-1)));
    assert_eq!(reap_tracked(&mut alive), Liveness::Alive);
    // try_alive Err → Unknown, слот сохранён
    let mut unk = Some(spawned(
        "id-1",
        FakeChild {
            alive_for: Cell::new(0),
            try_err: true,
            terminate_err_times: Cell::new(0),
            terminated: Rc::new(Cell::new(false)),
            waited: Rc::new(Cell::new(false)),
        },
    ));
    assert_eq!(reap_tracked(&mut unk), Liveness::Unknown);
    assert!(
        unk.is_some(),
        "Unknown НЕ должен чистить слот (fail-closed)"
    );
}

// ── 6. happy: [RustReady, PythonStarting, PythonReady], spawn ровно раз ───────
#[test]
fn supervise_happy_sequence() {
    let probe = FakeProbe::new(false, Some("id-1"));
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 2);
    probe.up.set(true); // backend поднялся, ID совпадает
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 2);
    assert_eq!(
        emits,
        vec![
            StartupState::RustReady,
            StartupState::PythonStarting,
            StartupState::PythonReady
        ]
    );
    assert_eq!(spawner.count, 1);
}

// ── 7. crash-storm: точное число спавнов + ровно один terminal emit ──────────
#[test]
fn supervise_crash_storm_exact_count_one_terminal() {
    let probe = FakeProbe::new(false, None);
    let mut spawner = FakeSpawner::new(0); // child умирает мгновенно
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    let ctrl = drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 300);
    assert_eq!(ctrl, LoopControl::Stop);
    assert_eq!(ctx.state, StartupState::Degraded(DegradedReason::GaveUp));
    assert_eq!(spawner.count, ctx.cap + 1, "ровно cap+1 спавнов");
    let terminals = emits
        .iter()
        .filter(|s| **s == StartupState::Degraded(DegradedReason::GaveUp))
        .count();
    assert_eq!(terminals, 1, "ровно один terminal emit");
}

// ── 8. no kill while alive ───────────────────────────────────────────────────
#[test]
fn supervise_no_kill_while_alive() {
    let probe = FakeProbe::new(false, None);
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 120);
    assert_eq!(ctx.state, StartupState::PythonStarting);
    assert!(!spawner.last_terminated.get());
    assert_eq!(spawner.count, 1);
}

// ── 9. wrong-ID (stale) + tracked child alive != Ready ───────────────────────
#[test]
fn supervise_stale_id_not_ready() {
    let probe = FakeProbe::new(true, Some("stale-id")); // backend отвечает чужим ID
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let mut ctx = ready_ctx();
    ctx.tracked = Some(spawned("id-1", FakeChild::new(-1))); // наш ID = id-1
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 4);
    assert_eq!(
        ctx.state,
        StartupState::Degraded(DegradedReason::ForeignBackend)
    );
    assert_ne!(ctx.state, StartupState::PythonReady);
    assert_eq!(spawner.count, 0);
}

// ── 10. instance-ID вращается после respawn ──────────────────────────────────
#[test]
fn supervise_instance_id_rotates_after_respawn() {
    let probe = FakeProbe::new(false, None);
    let mut spawner = FakeSpawner::new(0); // фаза 1: child умирает
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 2); // spawn#1 id-1
    let first = ctx.tracked.as_ref().map(|s| s.instance_id.clone());
    assert_eq!(first.as_deref(), Some("id-1"));
    spawner.alive_for = -1; // фаза 2: respawn остаётся живым
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 8);
    let id = ctx.tracked.as_ref().map(|s| s.instance_id.clone());
    assert!(id.is_some(), "живой respawn");
    assert_ne!(
        id, first,
        "respawn обязан получить НОВЫЙ instance-ID (вращение)"
    );
}

// ── 11. try_alive Err (Unknown) + OwnedHealthy != Ready, без spawn ───────────
#[test]
fn supervise_unknown_liveness_not_ready() {
    let probe = FakeProbe::new(true, Some("id-1")); // отвечает нашим ID
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let mut ctx = ready_ctx();
    ctx.tracked = Some(spawned(
        "id-1",
        FakeChild {
            alive_for: Cell::new(-1),
            try_err: true, // try_alive всегда Err → Unknown
            terminate_err_times: Cell::new(0),
            terminated: Rc::new(Cell::new(false)),
            waited: Rc::new(Cell::new(false)),
        },
    ));
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 4);
    assert_eq!(
        ctx.state,
        StartupState::Degraded(DegradedReason::ProcessStatusUnknown)
    );
    assert_ne!(ctx.state, StartupState::PythonReady);
    assert_eq!(
        spawner.count, 0,
        "Unknown liveness → НЕ spawn (handle сохранён)"
    );
    assert!(ctx.tracked.is_some());
}

// ── 12. shutdown ВНУТРИ spawn: успех termination — child убит до store ────────
#[test]
fn supervise_shutdown_inside_spawn_terminates_before_store() {
    let probe = FakeProbe::new(false, None);
    let sd = Arc::new(AtomicBool::new(false));
    let mut spawner = FakeSpawner::new(-1);
    spawner.set_shutdown_on_spawn = Some(sd.clone());
    let clk = clock();
    let mut ctx = ready_ctx();
    let ctrl = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &*sd, &mut |_| {});
    assert_eq!(ctrl, LoopControl::Stop);
    assert!(spawner.last_terminated.get(), "in-flight child terminated");
    assert!(
        spawner.last_waited.get(),
        "wait — часть успешной termination"
    );
    assert!(ctx.tracked.is_none(), "child НЕ сохранён (no orphan)");
}

// ── 13. post-spawn terminate error: child СОХРАНЁН для retry ─────────────────
#[test]
fn supervise_post_spawn_terminate_error_keeps_child() {
    let probe = FakeProbe::new(false, None);
    let sd = Arc::new(AtomicBool::new(false));
    let mut spawner = FakeSpawner::new(-1);
    spawner.terminate_err_times = 1; // termination упадёт один раз
    spawner.set_shutdown_on_spawn = Some(sd.clone());
    let clk = clock();
    let mut ctx = ready_ctx();
    let ctrl = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &*sd, &mut |_| {});
    assert_eq!(ctrl, LoopControl::Continue, "retry на следующем шаге");
    assert!(
        ctx.tracked.is_some(),
        "child сохранён для retry (не потерян)"
    );
    assert!(
        matches!(ctx.state, StartupState::Failed(_)),
        "KillFailed отражён"
    );
}

// ── 14. terminate error сохраняет slot; повтор чистит ────────────────────────
#[test]
fn stop_terminate_error_keeps_then_retry_clears() {
    let probe = FakeProbe::new(false, None);
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let sd = AtomicBool::new(true); // shutdown
    let mut ctx = ready_ctx();
    let terminated = Rc::new(Cell::new(false));
    ctx.tracked = Some(spawned(
        "id-1",
        FakeChild {
            alive_for: Cell::new(-1),
            try_err: false,
            terminate_err_times: Cell::new(1), // упадёт один раз
            terminated: terminated.clone(),
            waited: Rc::new(Cell::new(false)),
        },
    ));
    // шаг 1: terminate Err → slot сохранён, Continue
    let c1 = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &sd, &mut |_| {});
    assert_eq!(c1, LoopControl::Continue);
    assert!(ctx.tracked.is_some(), "terminate error сохраняет slot");
    assert!(!terminated.get());
    // шаг 2: terminate Ok → slot очищен, Stop
    let c2 = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &sd, &mut |_| {});
    assert_eq!(c2, LoopControl::Stop);
    assert!(ctx.tracked.is_none(), "повтор termination чистит slot");
    assert!(terminated.get());
}

// ── 15. Crashed эмитится и восстанавливается ─────────────────────────────────
#[test]
fn supervise_crashed_emits_and_recovers() {
    let probe = FakeProbe::new(false, None);
    let mut spawner = FakeSpawner::new(0); // фаза 1: падает
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 6);
    assert!(emits.contains(&StartupState::Degraded(DegradedReason::Crashed)));
    // фаза 2: живой respawn (id-2), health ещё не подтверждён
    spawner.alive_for = -1;
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 8);
    assert_eq!(ctx.state, StartupState::PythonStarting);
    // фаза 3: owned-healthy по актуальному ID → восстановление
    let id = ctx.tracked.as_ref().unwrap().instance_id.clone();
    *probe.serving_id.borrow_mut() = Some(id);
    probe.up.set(true);
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 3);
    assert_eq!(
        ctx.state,
        StartupState::PythonReady,
        "должно восстановиться"
    );
}

// ── 16. spawn-failure — distinct причина ─────────────────────────────────────
#[test]
fn supervise_spawn_failure_distinct_reason() {
    let probe = FakeProbe::new(false, None);
    let mut spawner = FakeSpawner::new(-1);
    spawner.fail = true;
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 4);
    assert!(emits.contains(&StartupState::Degraded(DegradedReason::SpawnFailed)));
    assert!(!emits.contains(&StartupState::Degraded(DegradedReason::Crashed)));
}

// ── 17. healthy не сбрасывает окно падений ───────────────────────────────────
#[test]
fn healthy_step_does_not_reset_failures() {
    let probe = FakeProbe::new(true, Some("id-1"));
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let mut ctx = ready_ctx();
    let now = clk.now();
    ctx.failures = vec![now, now];
    ctx.tracked = Some(spawned("id-1", FakeChild::new(-1)));
    let never = AtomicBool::new(false);
    let _ = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &never, &mut |_| {});
    assert_eq!(ctx.state, StartupState::PythonReady);
    assert_eq!(
        ctx.failures.len(),
        2,
        "healthy НЕ должен чистить окно падений"
    );
}

// ── 18. failures_in_window вытесняет старые ──────────────────────────────────
#[test]
fn failures_in_window_prunes_old() {
    let base = Instant::now();
    let window = Duration::from_secs(60);
    let now = base + Duration::from_secs(120);
    let failures = vec![base, now - Duration::from_secs(30), now];
    assert_eq!(failures_in_window(&failures, now, window), 2);
}
