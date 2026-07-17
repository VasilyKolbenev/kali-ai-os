//! Unit-тесты pure startup-ядра. Ноль реальных OS-процессов — всё через фейки.
use super::*;
use std::cell::Cell;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

// ── тест-даблы ───────────────────────────────────────────────────────────────
struct FakeChild {
    alive_for: Cell<i32>, // <0 бесконечно жив; 0 мёртв; >0 жив N вызовов
    try_err: bool,
    kill_err: bool,
    killed: Rc<Cell<bool>>,
}

impl FakeChild {
    fn alive(killed: Rc<Cell<bool>>) -> Self {
        FakeChild {
            alive_for: Cell::new(-1),
            try_err: false,
            kill_err: false,
            killed,
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
    fn kill(&mut self) -> std::io::Result<()> {
        self.killed.set(true);
        if self.kill_err {
            return Err(std::io::Error::new(std::io::ErrorKind::Other, "kill"));
        }
        Ok(())
    }
}

struct FakeSpawner {
    count: u32,
    alive_for: i32,
    fail: bool,
    killed: Rc<Cell<bool>>,
    set_shutdown_on_spawn: Option<Arc<AtomicBool>>,
}

impl FakeSpawner {
    fn new(alive_for: i32, killed: Rc<Cell<bool>>) -> Self {
        FakeSpawner {
            count: 0,
            alive_for,
            fail: false,
            killed,
            set_shutdown_on_spawn: None,
        }
    }
}

impl BackendSpawner for FakeSpawner {
    type Handle = FakeChild;
    fn spawn(&mut self) -> std::io::Result<FakeChild> {
        self.count += 1;
        if let Some(sd) = &self.set_shutdown_on_spawn {
            sd.store(true, Ordering::SeqCst); // shutdown выставлен ВНУТРИ spawn
        }
        if self.fail {
            return Err(std::io::Error::new(std::io::ErrorKind::Other, "spawn-fail"));
        }
        Ok(FakeChild {
            alive_for: Cell::new(self.alive_for),
            try_err: false,
            kill_err: false,
            killed: self.killed.clone(),
        })
    }
}

struct FakeProbe {
    status: Cell<ProbeStatus>,
}
impl HealthProbe for FakeProbe {
    fn status(&self) -> ProbeStatus {
        self.status.get()
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

/// Гоняет петлю с внешним «никогда-не-shutdown» сигналом.
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

// ── 1. classify truth-table (ownership) ──────────────────────────────────────
#[test]
fn classify_truth_table() {
    use ProbeStatus::*;
    assert_eq!(classify(true, OwnedHealthy), Action::Ready);
    assert_eq!(classify(true, Unhealthy), Action::Starting);
    assert_eq!(classify(true, ForeignHealthy), Action::Foreign); // конфликт по порту
    assert_eq!(classify(false, Unhealthy), Action::Spawn);
    assert_eq!(classify(false, OwnedHealthy), Action::Foreign); // наш ID, но нет живого child
    assert_eq!(classify(false, ForeignHealthy), Action::Foreign);
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

// ── 3. ПОЛНАЯ state×event matrix: total + инварианты ─────────────────────────
#[test]
fn next_state_full_matrix_invariants() {
    for s in all_states() {
        for ev in all_events() {
            let out = next_state(s.clone(), ev.clone());
            if is_terminal(&s) {
                assert_eq!(out, s, "терминал {s:?} должен поглощать {ev:?}");
                continue;
            }
            // Python*-события не порождают Python-состояние до RustReady
            if s == StartupState::ShellReady {
                let py = matches!(
                    ev,
                    HealthEvent::PythonHealthyOwned
                        | HealthEvent::PythonUnhealthyAlive
                        | HealthEvent::Crashed
                        | HealthEvent::SpawnFailed
                );
                if py {
                    assert_eq!(
                        out,
                        StartupState::ShellReady,
                        "Python* до RustReady: {ev:?}"
                    );
                }
            }
            // RustBindErr/GaveUp/KillFailed всегда терминальны (из не-терминала)
            match ev {
                HealthEvent::RustBindErr => {
                    assert_eq!(out, StartupState::Degraded(DegradedReason::PortOccupied))
                }
                HealthEvent::GaveUp => {
                    assert_eq!(out, StartupState::Degraded(DegradedReason::GaveUp))
                }
                HealthEvent::KillFailed => {
                    assert!(matches!(out, StartupState::Failed(_)))
                }
                _ => {}
            }
        }
    }
}

// ── 4. PythonReady идемпотентен ──────────────────────────────────────────────
#[test]
fn next_state_python_ready_idempotent() {
    let s = next_state(StartupState::RustReady, HealthEvent::PythonHealthyOwned);
    assert_eq!(s, StartupState::PythonReady);
    assert_eq!(
        next_state(s.clone(), HealthEvent::PythonHealthyOwned),
        StartupState::PythonReady
    );
}

// ── 5. RustBindErr терминален (никогда RustReady) ────────────────────────────
#[test]
fn next_state_rust_bind_err_terminal() {
    let s = next_state(StartupState::ShellReady, HealthEvent::RustBindErr);
    assert_eq!(s, StartupState::Degraded(DegradedReason::PortOccupied));
    assert_eq!(next_state(s.clone(), HealthEvent::RustBindOk), s);
}

// ── 6. ForeignHealthy → Degraded(ForeignBackend), не Ready ───────────────────
#[test]
fn next_state_foreign_healthy_not_ready() {
    assert_eq!(
        next_state(StartupState::RustReady, HealthEvent::ForeignHealthy),
        StartupState::Degraded(DegradedReason::ForeignBackend)
    );
}

// ── 7. PythonReady требует owned health ──────────────────────────────────────
#[test]
fn python_ready_requires_owned_health() {
    assert_eq!(
        next_state(StartupState::RustReady, HealthEvent::PythonHealthyOwned),
        StartupState::PythonReady
    );
    assert_ne!(
        next_state(StartupState::RustReady, HealthEvent::ForeignHealthy),
        StartupState::PythonReady
    );
}

// ── 8. resolve_backend_path порядок ──────────────────────────────────────────
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

// ── 9. reap до решения ───────────────────────────────────────────────────────
#[test]
fn reap_before_decision() {
    let killed = Rc::new(Cell::new(false));
    let mut slot = Some(FakeChild {
        alive_for: Cell::new(0),
        try_err: false,
        kill_err: false,
        killed: killed.clone(),
    });
    assert!(!reap_tracked(&mut slot));
    assert!(slot.is_none());
    let mut slot2 = Some(FakeChild::alive(killed));
    assert!(reap_tracked(&mut slot2));
    assert!(slot2.is_some());
}

// ── 9b. try_wait error: fail-closed (slot не очищен, alive=true) ─────────────
#[test]
fn reap_try_wait_error_keeps_slot_fail_closed() {
    let killed = Rc::new(Cell::new(false));
    let mut slot = Some(FakeChild {
        alive_for: Cell::new(0), // «мёртв», но try_err перекрывает
        try_err: true,
        kill_err: false,
        killed,
    });
    assert!(
        reap_tracked(&mut slot),
        "ошибка try_wait ⇒ трактуем как alive"
    );
    assert!(slot.is_some(), "ошибка try_wait НЕ должна очищать slot");
    // и классификация alive → не Spawn
    assert_ne!(classify(true, ProbeStatus::Unhealthy), Action::Spawn);
}

// ── 9c. supervise: try_wait error не спавнит второй backend ──────────────────
#[test]
fn supervise_try_wait_error_never_spawns_second() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed.clone());
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    ctx.state = StartupState::RustReady;
    ctx.child = Some(FakeChild {
        alive_for: Cell::new(0),
        try_err: true, // reap всегда «alive» (fail-closed)
        kill_err: false,
        killed,
    });
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 10);
    assert_eq!(
        spawner.count, 0,
        "fail-closed: второй backend не запускается"
    );
    assert!(ctx.child.is_some());
}

// ── 10. happy: [RustReady, PythonStarting, PythonReady], spawn ровно раз ──────
#[test]
fn supervise_loop_happy_sequence() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed);
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 2);
    probe.status.set(ProbeStatus::OwnedHealthy);
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

// ── 11. crash-storm: точное число спавнов + ровно один terminal emit ─────────
#[test]
fn supervise_crash_storm_exact_count_one_terminal() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(0, killed); // child умирает мгновенно
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    let ctrl = drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 300);
    assert_eq!(ctrl, LoopControl::Stop);
    assert_eq!(ctx.state, StartupState::Degraded(DegradedReason::GaveUp));
    assert_eq!(
        spawner.count,
        ctx.cap + 1,
        "ровно cap+1 спавнов (1 initial + cap retry)"
    );
    let terminals = emits
        .iter()
        .filter(|s| **s == StartupState::Degraded(DegradedReason::GaveUp))
        .count();
    assert_eq!(terminals, 1, "ровно один terminal emit");
}

// ── 12. no kill while alive (защита 30-60с OPUS-102 load) ─────────────────────
#[test]
fn supervise_no_kill_while_alive() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed.clone());
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 120);
    assert_eq!(ctx.state, StartupState::PythonStarting);
    assert!(!killed.get());
    assert_eq!(spawner.count, 1);
}

// ── 13. wrong-ID + tracked child alive != PythonReady ────────────────────────
#[test]
fn supervise_foreign_id_alive_child_not_ready() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::ForeignHealthy),
    }; // чужой ID
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed.clone());
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    ctx.state = StartupState::RustReady;
    ctx.child = Some(FakeChild::alive(killed)); // наш child жив
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 4);
    assert_eq!(
        ctx.state,
        StartupState::Degraded(DegradedReason::ForeignBackend)
    );
    assert_ne!(ctx.state, StartupState::PythonReady);
    assert_eq!(spawner.count, 0);
}

// ── 14. shutdown ВНУТРИ spawn убивает child до store ─────────────────────────
#[test]
fn supervise_shutdown_inside_spawn_kills_before_store() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let sd = Arc::new(AtomicBool::new(false));
    let mut spawner = FakeSpawner::new(-1, killed.clone());
    spawner.set_shutdown_on_spawn = Some(sd.clone()); // spawn() выставит shutdown
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    ctx.state = StartupState::RustReady;
    let ctrl = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &*sd, &mut |_| {});
    assert_eq!(ctrl, LoopControl::Stop);
    assert!(
        killed.get(),
        "in-flight child при shutdown должен быть убит"
    );
    assert!(
        ctx.child.is_none(),
        "child НЕ должен быть сохранён (no orphan)"
    );
    assert_eq!(spawner.count, 1);
}

// ── 15. Crashed реально эмитится и восстанавливается ─────────────────────────
#[test]
fn supervise_crashed_emits_and_recovers() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(0, killed); // фаза 1: child умирает
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 6);
    assert!(
        emits.contains(&StartupState::Degraded(DegradedReason::Crashed)),
        "падение обязано эмитить Degraded(Crashed): {emits:?}"
    );
    // фаза 2: живой respawn, но health ещё не подтверждён (probe Unhealthy —
    // реалистично: мёртвый процесс не отвечал бы healthy). Ожидаем PythonStarting.
    spawner.alive_for = -1;
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 8);
    assert!(ctx.child.is_some(), "живой respawn");
    assert_eq!(ctx.state, StartupState::PythonStarting);
    // фаза 3: backend стал owned-healthy → восстановление.
    probe.status.set(ProbeStatus::OwnedHealthy);
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 3);
    assert_eq!(
        ctx.state,
        StartupState::PythonReady,
        "должно восстановиться"
    );
    assert!(emits.contains(&StartupState::PythonStarting));
}

// ── 16. spawn-failure — distinct причина (не Crashed/loading) ─────────────────
#[test]
fn supervise_spawn_failure_distinct_reason() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed);
    spawner.fail = true; // spawn() всегда падает
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    let mut emits = Vec::new();
    drive(&mut ctx, &probe, &mut spawner, &clk, &mut emits, 4);
    assert!(
        emits.contains(&StartupState::Degraded(DegradedReason::SpawnFailed)),
        "spawn-failure ⇒ Degraded(SpawnFailed): {emits:?}"
    );
    assert!(!emits.contains(&StartupState::Degraded(DegradedReason::Crashed)));
}

// ── 17. healthy не сбрасывает окно падений ───────────────────────────────────
#[test]
fn healthy_step_does_not_reset_failures() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::OwnedHealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed);
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    ctx.state = StartupState::RustReady;
    let now = clk.now();
    ctx.failures = vec![now, now];
    ctx.child = Some(FakeChild::alive(Rc::new(Cell::new(false))));
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

// ── 19. kill error при shutdown отражается в состоянии ───────────────────────
#[test]
fn shutdown_kill_error_reflected_in_state() {
    let probe = FakeProbe {
        status: Cell::new(ProbeStatus::Unhealthy),
    };
    let killed = Rc::new(Cell::new(false));
    let mut spawner = FakeSpawner::new(-1, killed.clone());
    let clk = clock();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(true);
    ctx.state = StartupState::RustReady;
    ctx.child = Some(FakeChild {
        alive_for: Cell::new(-1),
        try_err: false,
        kill_err: true, // kill вернёт Err
        killed,
    });
    let sd = AtomicBool::new(true); // shutdown
    let mut emits = Vec::new();
    let ctrl = supervise_step(&mut ctx, &probe, &mut spawner, &clk, &sd, &mut |s| {
        emits.push(s)
    });
    assert_eq!(ctrl, LoopControl::Stop);
    assert!(
        matches!(ctx.state, StartupState::Failed(_)),
        "kill error → Failed"
    );
}
