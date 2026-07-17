//! Юнит-тесты runtime-адаптеров desktop-shell (lib.rs).
use super::*;
use std::io::Write;
use std::sync::atomic::AtomicUsize;
use std::sync::mpsc;

// ── classify_health ──────────────────────────────────────────────────────────
#[test]
fn classify_health_matching_id_owned() {
    let body = r#"{"status":"ok","desktop_instance_id":"id-1"}"#;
    assert_eq!(
        classify_health(200, body, Some("id-1")),
        ProbeStatus::OwnedHealthy
    );
}

#[test]
fn classify_health_wrong_id_foreign() {
    assert_eq!(
        classify_health(200, r#"{"desktop_instance_id":"other"}"#, Some("id-1")),
        ProbeStatus::ForeignHealthy
    );
}

#[test]
fn classify_health_missing_id_foreign() {
    // ручной запуск: desktop_instance_id == null/absent
    assert_eq!(
        classify_health(200, r#"{"status":"ok"}"#, Some("id-1")),
        ProbeStatus::ForeignHealthy
    );
}

#[test]
fn classify_health_non_200_unhealthy() {
    assert_eq!(
        classify_health(503, "{}", Some("id-1")),
        ProbeStatus::Unhealthy
    );
}

#[test]
fn classify_health_bad_json_foreign_not_panic() {
    assert_eq!(
        classify_health(200, "not-json", Some("id-1")),
        ProbeStatus::ForeignHealthy
    );
}

// ── RealChild::terminate_and_wait (race-safe, через RawProc-seam) ─────────────
struct FakeProc {
    exited_seq: Vec<bool>,
    idx: usize,
    kill_err: bool,
    kill_called: bool,
    wait_called: bool,
}

impl RawProc for FakeProc {
    fn poll_exited(&mut self) -> std::io::Result<bool> {
        let v = self.exited_seq.get(self.idx).copied().unwrap_or(false);
        self.idx += 1;
        Ok(v)
    }
    fn kill(&mut self) -> std::io::Result<()> {
        self.kill_called = true;
        if self.kill_err {
            Err(std::io::Error::new(std::io::ErrorKind::Other, "kill"))
        } else {
            Ok(())
        }
    }
    fn wait(&mut self) -> std::io::Result<()> {
        self.wait_called = true;
        Ok(())
    }
}

fn fake_child(seq: &[bool], kill_err: bool) -> RealChild<FakeProc> {
    RealChild(FakeProc {
        exited_seq: seq.to_vec(),
        idx: 0,
        kill_err,
        kill_called: false,
        wait_called: false,
    })
}

#[test]
fn terminate_already_exited_no_kill_no_wait() {
    let mut c = fake_child(&[true], false);
    assert!(c.terminate_and_wait().is_ok());
    assert!(!c.0.kill_called, "уже завершён → kill не нужен");
    assert!(!c.0.wait_called, "уже завершён → без blocking wait");
}

#[test]
fn terminate_alive_kills_then_waits() {
    let mut c = fake_child(&[false], false);
    assert!(c.terminate_and_wait().is_ok());
    assert!(c.0.kill_called);
    assert!(c.0.wait_called, "живой → kill затем wait");
}

#[test]
fn terminate_kill_error_no_blocking_wait() {
    // жив; kill Err; повторный poll всё ещё жив → исходная ошибка, wait НЕ вызван.
    let mut c = fake_child(&[false, false], true);
    assert!(c.terminate_and_wait().is_err(), "kill-ошибка проброшена");
    assert!(c.0.kill_called);
    assert!(
        !c.0.wait_called,
        "kill-ошибка НЕ должна вызывать blocking wait"
    );
}

#[test]
fn terminate_exited_between_check_and_kill_success() {
    // жив; kill Err; но повторный poll показал exit → success, без wait.
    let mut c = fake_child(&[false, true], true);
    assert!(
        c.terminate_and_wait().is_ok(),
        "вышел между check и kill → success"
    );
    assert!(!c.0.wait_called);
}

// ── RealProbe: зависший listener не блокирует (bounded timeouts) ──────────────
#[test]
fn real_probe_hung_listener_times_out_unhealthy() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    std::thread::spawn(move || {
        // принять соединение и НЕ отвечать (зависший бэкенд).
        if let Ok((stream, _)) = listener.accept() {
            std::thread::sleep(Duration::from_secs(30));
            drop(stream);
        }
    });
    let probe = RealProbe::with_url(format!("http://{addr}/health"));
    let start = Instant::now();
    let status = probe.status(Some("id-1"));
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "зависший listener не должен блокировать (elapsed {:?})",
        start.elapsed()
    );
    assert_eq!(status, ProbeStatus::Unhealthy);
}

// ── Shutdown-оркестрация: waiter вне event-loop, done только по ack ───────────
fn mk_shutdown() -> (ShutdownControl, mpsc::Sender<()>) {
    let (tx, rx) = mpsc::channel::<()>();
    (
        ShutdownControl {
            flag: Arc::new(AtomicBool::new(false)),
            waker: Arc::new(Waker::new()),
            ack: Mutex::new(Some(rx)),
            done: Arc::new(AtomicBool::new(false)),
            waiter_started: AtomicBool::new(false),
        },
        tx,
    )
}

const TICK: Duration = Duration::from_millis(20);

#[test]
fn shutdown_done_allows_exit_without_waiter() {
    let (ctl, _tx) = mk_shutdown();
    ctl.done.store(true, Ordering::SeqCst);
    let n = Arc::new(AtomicUsize::new(0));
    let n2 = n.clone();
    let d = on_exit_requested(&ctl, TICK, move || {
        n2.fetch_add(1, Ordering::SeqCst);
    });
    assert_eq!(d, ExitDecision::Allow);
    assert_eq!(n.load(Ordering::SeqCst), 0, "done → без waiter/on_complete");
    assert!(!ctl.waiter_started.load(Ordering::SeqCst));
}

#[test]
fn shutdown_pending_prevents_starts_one_waiter_completes_once() {
    let (ctl, tx) = mk_shutdown();
    let n = Arc::new(AtomicUsize::new(0));
    // ExitRequested #1 → Prevent, стартует РОВНО один waiter.
    let n1 = n.clone();
    assert_eq!(
        on_exit_requested(&ctl, TICK, move || {
            n1.fetch_add(1, Ordering::SeqCst);
        }),
        ExitDecision::Prevent
    );
    assert!(ctl.waiter_started.load(Ordering::SeqCst));
    // ExitRequested #2 до ack → всё ещё Prevent, второй waiter НЕ стартует.
    let n2 = n.clone();
    assert_eq!(
        on_exit_requested(&ctl, TICK, move || {
            n2.fetch_add(1, Ordering::SeqCst);
        }),
        ExitDecision::Prevent
    );
    // поздний ack (после нескольких timeout-циклов waiter'а — auto-continue).
    std::thread::sleep(Duration::from_millis(60));
    tx.send(()).unwrap();
    std::thread::sleep(Duration::from_millis(80));
    assert_eq!(
        n.load(Ordering::SeqCst),
        1,
        "completion callback ровно один раз"
    );
    assert!(
        ctl.done.load(Ordering::SeqCst),
        "done после подтверждённого ack"
    );
}

#[test]
fn shutdown_disconnected_never_completes_pending_terminal() {
    let (ctl, tx) = mk_shutdown();
    let n = Arc::new(AtomicUsize::new(0));
    let n1 = n.clone();
    assert_eq!(
        on_exit_requested(&ctl, TICK, move || {
            n1.fetch_add(1, Ordering::SeqCst);
        }),
        ExitDecision::Prevent
    );
    drop(tx); // supervisor «умер» без ack
    std::thread::sleep(Duration::from_millis(60));
    assert_eq!(n.load(Ordering::SeqCst), 0, "disconnected → без completion");
    assert!(
        !ctl.done.load(Ordering::SeqCst),
        "disconnected НИКОГДА не Completed"
    );
    // повторный запрос всё ещё НЕ Allow — pending остаётся terminal.
    let n2 = n.clone();
    assert_eq!(
        on_exit_requested(&ctl, TICK, move || {
            n2.fetch_add(1, Ordering::SeqCst);
        }),
        ExitDecision::Prevent,
        "повторный ExitRequested не может разрешить выход"
    );
}

#[test]
fn wait_for_ack_disconnected() {
    let (tx, rx) = mpsc::channel::<()>();
    drop(tx);
    assert_eq!(
        wait_for_ack(&rx, Duration::from_millis(10)),
        AckOutcome::Disconnected
    );
}

#[test]
fn wait_for_ack_completes_after_timeout_cycles() {
    let (tx, rx) = mpsc::channel::<()>();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(50)); // несколько tick-циклов
        let _ = tx.send(());
    });
    assert_eq!(
        wait_for_ack(&rx, Duration::from_millis(10)),
        AckOutcome::Completed
    );
}

// ── Waker: wake-before-wait возвращается сразу, затем флаг сброшен ────────────
#[test]
fn waker_lost_wake_returns_immediately_then_resets() {
    let w = Waker::new();
    w.wake(); // wake ДО wait
    let start = Instant::now();
    w.wait(Duration::from_secs(10));
    assert!(
        start.elapsed() < Duration::from_millis(500),
        "wake-before-wait должен вернуться сразу"
    );
    // флаг сброшен: следующий wait без wake ждёт таймаут.
    let start2 = Instant::now();
    w.wait(Duration::from_millis(80));
    assert!(
        start2.elapsed() >= Duration::from_millis(60),
        "после consume флаг сброшен → wait ждёт таймаут"
    );
}

// ── Логи: append переживает respawn (crash-маркер сохраняется) ────────────────
#[test]
fn logs_append_marker_survives_respawn() {
    let dir = std::env::temp_dir().join(format!("kali-log-test-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    // spawn #1: crash-маркер.
    {
        let (mut out, _err) = open_backend_logs(&dir).unwrap();
        writeln!(out, "CRASH-MARKER-1").unwrap();
    }
    // spawn #2: append (НЕ truncate).
    {
        let (mut out, _err) = open_backend_logs(&dir).unwrap();
        writeln!(out, "SPAWN-2").unwrap();
    }
    let content = fs::read_to_string(dir.join("kali-backend.out.log")).unwrap();
    assert!(
        content.contains("CRASH-MARKER-1"),
        "маркер должен пережить respawn"
    );
    assert!(content.contains("SPAWN-2"));
    let _ = fs::remove_dir_all(&dir);
}
