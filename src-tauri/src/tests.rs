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
    // ExitRequested #1 → Prevent, стартует РОВНО один waiter (возвращает JoinHandle).
    let n1 = n.clone();
    let (d1, h1) = spawn_exit_waiter(&ctl, TICK, move || {
        n1.fetch_add(1, Ordering::SeqCst);
    });
    assert_eq!(d1, ExitDecision::Prevent);
    assert!(ctl.waiter_started.load(Ordering::SeqCst));
    let waiter = h1.expect("первый ExitRequested должен запустить waiter");

    // ExitRequested #2 до ack → всё ещё Prevent, второй waiter НЕ стартует (handle None).
    let n2 = n.clone();
    let (d2, h2) = spawn_exit_waiter(&ctl, TICK, move || {
        n2.fetch_add(1, Ordering::SeqCst);
    });
    assert_eq!(d2, ExitDecision::Prevent);
    assert!(h2.is_none(), "второй waiter не должен стартовать");

    // ack → waiter завершает Completed-ветку. Синхронизация — join() (без wall-clock):
    // waiter ставит done=true, затем on_complete (n+=1), затем поток выходит; join
    // наблюдает всё это по happens-before. Скорость планировщика роли не играет.
    tx.send(()).unwrap();
    waiter.join().expect("waiter поток завершается");

    assert!(
        ctl.done.load(Ordering::SeqCst),
        "done после подтверждённого ack"
    );
    assert_eq!(
        n.load(Ordering::SeqCst),
        1,
        "completion callback ровно один раз"
    );
}

#[test]
fn shutdown_disconnected_never_completes_pending_terminal() {
    let (ctl, tx) = mk_shutdown();
    let n = Arc::new(AtomicUsize::new(0));
    let n1 = n.clone();
    let (d1, h1) = spawn_exit_waiter(&ctl, TICK, move || {
        n1.fetch_add(1, Ordering::SeqCst);
    });
    assert_eq!(d1, ExitDecision::Prevent);
    let waiter = h1.expect("первый ExitRequested должен запустить waiter");

    drop(tx); // supervisor «умер» без ack → wait_for_ack вернёт Disconnected
              // Синхронизация — join() (без wall-clock): после выхода waiter'а
              // Disconnected-ветка гарантированно отработала и НЕ тронула done/callback.
    waiter.join().expect("waiter завершается по Disconnected");

    assert_eq!(n.load(Ordering::SeqCst), 0, "disconnected → без completion");
    assert!(
        !ctl.done.load(Ordering::SeqCst),
        "disconnected НИКОГДА не Completed"
    );
    // повторный запрос всё ещё НЕ Allow — pending остаётся terminal.
    let n2 = n.clone();
    let (d2, _h2) = spawn_exit_waiter(&ctl, TICK, move || {
        n2.fetch_add(1, Ordering::SeqCst);
    });
    assert_eq!(
        d2,
        ExitDecision::Prevent,
        "повторный ExitRequested не может разрешить выход"
    );
}

// Production adapter: через реальный вход on_exit_requested() (обёртка), НЕ seam.
// Если обёртка перестанет запускать waiter — waiter_started/completion не наступят
// и тест покраснеет. Синхронизация — completion channel (recv = bounded watchdog).
#[test]
fn on_exit_requested_wrapper_completes_then_allows() {
    let (ctl, tx) = mk_shutdown();
    let (done_tx, done_rx) = mpsc::channel::<()>();
    let n = Arc::new(AtomicUsize::new(0));

    // Pending → Prevent через production-вход.
    let n1 = n.clone();
    let d1 = on_exit_requested(&ctl, TICK, move || {
        n1.fetch_add(1, Ordering::SeqCst);
        let _ = done_tx.send(());
    });
    assert_eq!(d1, ExitDecision::Prevent);
    assert!(ctl.flag.load(Ordering::SeqCst), "flag выставлен");
    assert!(
        ctl.waiter_started.load(Ordering::SeqCst),
        "обёртка обязана запустить waiter"
    );

    // ack → callback гарантированно завершается (recv — bounded watchdog, не sleep).
    tx.send(()).unwrap();
    done_rx
        .recv_timeout(Duration::from_secs(10))
        .expect("callback должен выполниться после ack");
    // Порядок в waiter'е: done=true ПЕРЕД on_complete → done виден после recv.
    assert!(
        ctl.done.load(Ordering::SeqCst),
        "done=true после подтверждённого ack"
    );
    assert_eq!(n.load(Ordering::SeqCst), 1, "callback ровно один раз");

    // Повторный on_exit_requested после done → Allow и без нового callback.
    let n2 = n.clone();
    let d2 = on_exit_requested(&ctl, TICK, move || {
        n2.fetch_add(1, Ordering::SeqCst);
    });
    assert_eq!(d2, ExitDecision::Allow, "done → Allow");
    assert_eq!(
        n.load(Ordering::SeqCst),
        1,
        "второй on_exit_requested не вызывает callback"
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

// Детерминированно (без sleep-как-доказательства): наблюдатель сигналит о РЕАЛЬНОМ
// Timeout-цикле; только ПОСЛЕ этого тест шлёт ack; waiter обязан вернуть Completed.
// Порядок доказан: Timeout observed → send ack → Completed.
#[test]
fn wait_for_ack_survives_timeout_then_completes() {
    let (tx, rx) = mpsc::channel::<()>();
    let (obs_tx, obs_rx) = mpsc::channel::<()>(); // waiter → тест: «пережил Timeout»
    let (out_tx, out_rx) = mpsc::channel::<AckOutcome>(); // исход waiter'а (bounded sync)

    // ack НЕ послан → recv_timeout гарантированно вернёт Timeout ≥1 раз.
    let waiter = std::thread::spawn(move || {
        let outcome = wait_for_ack_with_timeout_observer(&rx, TICK, || {
            let _ = obs_tx.send(());
        });
        let _ = out_tx.send(outcome);
    });

    // Ждём ЯВНОГО подтверждения ≥1 Timeout-цикла (recv — bounded watchdog теста,
    // не способ «подождать достаточно»).
    obs_rx
        .recv_timeout(Duration::from_secs(10))
        .expect("waiter должен пережить минимум один Timeout-цикл");
    // Только теперь, после observed Timeout, отправляем ack.
    tx.send(()).unwrap();

    // Waiter обязан вернуть Completed. out_rx — bounded watchdog: если ack «потерян»
    // (Ok-ветка сломана), waiter не пришлёт исход → recv истечёт → RED (не hang).
    let outcome = out_rx
        .recv_timeout(Duration::from_secs(10))
        .expect("waiter завершается после ack");
    assert_eq!(
        outcome,
        AckOutcome::Completed,
        "после observed Timeout + ack → Completed"
    );
    waiter.join().expect("поток завершается"); // достижимо только на success-пути
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
