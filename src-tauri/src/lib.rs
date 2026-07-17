pub mod backend;
mod startup;

use std::fs::{self, File, OpenOptions};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender, TryRecvError};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

use startup::{
    BindOutcome, ChildHandle, HealthProbe, LoopControl, ProbeStatus, Spawned, StartupState,
    SuperviseCtx,
};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: &str = "3005";
const BACKEND_HEALTH_URL: &str = "http://127.0.0.1:3005/health";
const BACKEND_CORS_ORIGINS: &str = "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://localhost:1420,http://127.0.0.1:1420,http://localhost:1421,http://127.0.0.1:1421";
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;
/// Событие смены startup-состояния для фронта.
const STARTUP_EVENT: &str = "startup://state";
/// Период тика supervisor (пробуждается раньше по shutdown через Condvar).
const SUPERVISOR_TICK: Duration = Duration::from_millis(500);
/// Ограниченное ожидание ack при shutdown (bounded).
const SHUTDOWN_ACK_TIMEOUT: Duration = Duration::from_secs(5);
/// Предел тела /health (защита от зависшего/огромного ответа).
const HEALTH_BODY_LIMIT: u64 = 64 * 1024;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to KALI.", name)
}

/// Level-triggered authoritative startup-состояние + метрики first-paint.
struct StartupCell {
    label: Mutex<String>,
    t0: Instant,
    t_paint: Mutex<Option<Instant>>,
}

/// Condvar-будильник: supervisor спит на нём (без busy-wait), shutdown будит.
/// `wait` использует predicate — wake-before-wait возвращается сразу, а после
/// consume флаг сбрасывается (устойчиво к lost-wake).
struct Waker {
    m: Mutex<bool>,
    cv: Condvar,
}

impl Waker {
    fn new() -> Self {
        Waker {
            m: Mutex::new(false),
            cv: Condvar::new(),
        }
    }
    fn wait(&self, dur: Duration) {
        let guard = self.m.lock().unwrap();
        let (mut guard, _) = self
            .cv
            .wait_timeout_while(guard, dur, |woken| !*woken)
            .unwrap();
        *guard = false; // consume: сброс флага
    }
    fn wake(&self) {
        *self.m.lock().unwrap() = true;
        self.cv.notify_all();
    }
}

/// Результат попытки graceful shutdown.
#[derive(Debug, PartialEq, Eq)]
enum ShutdownResult {
    Completed,
    Timeout,
    Disconnected,
}

/// Идемпотентный shutdown: флаг + будильник + ack. `done` ставится ТОЛЬКО после
/// подтверждённого ack; при timeout receiver сохраняется (cleanup retryable).
struct ShutdownControl {
    flag: Arc<AtomicBool>,
    waker: Arc<Waker>,
    ack: Mutex<Option<Receiver<()>>>,
    done: AtomicBool,
}

/// Попытка graceful shutdown с ограниченным ожиданием ack.
fn attempt_shutdown(ctl: &ShutdownControl, timeout: Duration) -> ShutdownResult {
    if ctl.done.load(Ordering::SeqCst) {
        return ShutdownResult::Completed;
    }
    ctl.flag.store(true, Ordering::SeqCst);
    ctl.waker.wake();
    let mut guard = ctl.ack.lock().unwrap();
    let recv = match guard.take() {
        Some(r) => r,
        None => return ShutdownResult::Completed,
    };
    match recv.recv_timeout(timeout) {
        Ok(()) => {
            ctl.done.store(true, Ordering::SeqCst);
            ShutdownResult::Completed
        }
        Err(RecvTimeoutError::Timeout) => {
            *guard = Some(recv); // не терять receiver → cleanup retryable
            ShutdownResult::Timeout
        }
        Err(RecvTimeoutError::Disconnected) => ShutdownResult::Disconnected,
    }
}

/// Только выставить флаг+wake (Destroyed): не потребляет ack.
fn signal_shutdown_only(ctl: &ShutdownControl) {
    ctl.flag.store(true, Ordering::SeqCst);
    ctl.waker.wake();
}

/// Машинный label состояния (фронт мапит 1:1); pure-enum остаётся Tauri-free.
fn state_label(s: &StartupState) -> String {
    use startup::DegradedReason as D;
    match s {
        StartupState::ShellReady => "shell_ready".into(),
        StartupState::RustReady => "rust_ready".into(),
        StartupState::PythonStarting => "python_starting".into(),
        StartupState::PythonReady => "python_ready".into(),
        StartupState::Degraded(D::PortOccupied) => "degraded:port_occupied".into(),
        StartupState::Degraded(D::ForeignBackend) => "degraded:foreign_backend".into(),
        StartupState::Degraded(D::NotFound) => "degraded:not_found".into(),
        StartupState::Degraded(D::Crashed) => "degraded:crashed".into(),
        StartupState::Degraded(D::SpawnFailed) => "degraded:spawn_failed".into(),
        StartupState::Degraded(D::ProcessStatusUnknown) => "degraded:process_unknown".into(),
        StartupState::Degraded(D::RustStartupFailed) => "failed:rust_startup".into(),
        StartupState::Degraded(D::GaveUp) => "failed:gave_up".into(),
        StartupState::Failed(_) => "failed".into(),
    }
}

/// Authoritative startup-состояние для фронта. Level-triggered: пропущенный
/// emit самолечится на следующем poll. Первый вызов фиксирует t_paint.
#[tauri::command]
fn get_startup_state(app: AppHandle) -> String {
    let cell = app.state::<StartupCell>();
    {
        let mut p = cell.t_paint.lock().unwrap();
        if p.is_none() {
            let paint = Instant::now();
            *p = Some(paint);
            let ms = paint.duration_since(cell.t0).as_millis();
            eprintln!("first paint: get_startup_state at {ms} ms since t0");
        }
    }
    let label = cell.label.lock().unwrap().clone();
    label
}

fn runtime_data_dir() -> PathBuf {
    match std::env::var_os("APPDATA") {
        Some(path) => PathBuf::from(path).join("KALI"),
        None => std::env::current_exe()
            .ok()
            .and_then(|path| path.parent().map(|dir| dir.to_path_buf()))
            .unwrap_or_else(|| PathBuf::from("."))
            .join("data"),
    }
}

/// Открыть backend-логи в APPEND-режиме (respawn НЕ truncate: crash-маркер из
/// spawn #1 переживает spawn #2).
fn open_backend_logs(logs_dir: &Path) -> std::io::Result<(File, File)> {
    fs::create_dir_all(logs_dir)?;
    let open = |name: &str| {
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs_dir.join(name))
    };
    Ok((open("kali-backend.out.log")?, open("kali-backend.err.log")?))
}

/// Путь backend через pure `resolve_backend_path` (реальная FS-проба).
fn find_backend() -> Option<PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));
    startup::resolve_backend_path(exe_dir.as_deref(), |p| p.exists())
}

// ── реальные адаптеры pure-трейтов ───────────────────────────────────────────

/// Минимальные ops над дочерним процессом (seam для тестирования terminate-гонки).
trait RawProc {
    /// `true` = процесс завершён (reaped).
    fn poll_exited(&mut self) -> std::io::Result<bool>;
    fn kill(&mut self) -> std::io::Result<()>;
    fn wait(&mut self) -> std::io::Result<()>;
}

impl RawProc for Child {
    fn poll_exited(&mut self) -> std::io::Result<bool> {
        Ok(self.try_wait()?.is_some())
    }
    fn kill(&mut self) -> std::io::Result<()> {
        Child::kill(self)
    }
    fn wait(&mut self) -> std::io::Result<()> {
        Child::wait(self).map(|_| ())
    }
}

/// Обёртка над процессом, реализующая `ChildHandle` (обобщена по `RawProc`).
struct RealChild<P: RawProc>(P);

impl<P: RawProc> ChildHandle for RealChild<P> {
    fn try_alive(&mut self) -> std::io::Result<bool> {
        Ok(!self.0.poll_exited()?)
    }
    fn terminate_and_wait(&mut self) -> std::io::Result<()> {
        if self.0.poll_exited()? {
            return Ok(()); // уже завершён → без blocking wait
        }
        match self.0.kill() {
            Ok(()) => self.0.wait(), // жив → kill затем wait (wait — часть успеха)
            Err(kill_err) => {
                // race: процесс мог выйти между poll и kill. Проверяем НЕблокирующе;
                // exit → success, иначе исходная kill-ошибка (без blocking wait).
                match self.0.poll_exited() {
                    Ok(true) => Ok(()),
                    _ => Err(kill_err),
                }
            }
        }
    }
}

/// Отобразить HTTP-ответ :3005/health в `ProbeStatus` (ownership по instance-ID).
fn classify_health(status: u16, body: &str, expected: Option<&str>) -> ProbeStatus {
    if status != 200 {
        return ProbeStatus::Unhealthy;
    }
    let served = serde_json::from_str::<serde_json::Value>(body)
        .ok()
        .and_then(|v| {
            v.get("desktop_instance_id")
                .and_then(|x| x.as_str())
                .map(str::to_string)
        });
    match (expected, served.as_deref()) {
        (Some(e), Some(s)) if e == s => ProbeStatus::OwnedHealthy,
        _ => ProbeStatus::ForeignHealthy,
    }
}

/// Reusable ureq-agent с bounded-таймаутами (зависший listener не блокирует).
fn probe_agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(2)))
        .timeout_connect(Some(Duration::from_secs(1)))
        .timeout_recv_response(Some(Duration::from_secs(2)))
        .timeout_recv_body(Some(Duration::from_secs(2)))
        .build()
        .new_agent()
}

/// Реальный HealthProbe: один reusable agent; GET /health, сверка instance-ID.
struct RealProbe {
    agent: ureq::Agent,
    url: String,
}

impl RealProbe {
    fn new() -> Self {
        RealProbe {
            agent: probe_agent(),
            url: BACKEND_HEALTH_URL.to_string(),
        }
    }
    #[cfg(test)]
    fn with_url(url: String) -> Self {
        RealProbe {
            agent: probe_agent(),
            url,
        }
    }
}

impl HealthProbe for RealProbe {
    fn status(&self, expected: Option<&str>) -> ProbeStatus {
        match self.agent.get(&self.url).call() {
            Ok(mut resp) => {
                let code = resp.status().as_u16();
                let body = resp
                    .body_mut()
                    .with_config()
                    .limit(HEALTH_BODY_LIMIT)
                    .read_to_string()
                    .unwrap_or_default();
                classify_health(code, &body, expected)
            }
            // connection failure / timeout → бэкенд не отвечает.
            Err(_) => ProbeStatus::Unhealthy,
        }
    }
}

/// Реальный spawner: свежий per-spawn UUID → env → `kali-backend.exe`.
struct RealSpawner;

impl startup::BackendSpawner for RealSpawner {
    type Handle = RealChild<Child>;
    fn spawn(&mut self) -> std::io::Result<Spawned<RealChild<Child>>> {
        let backend_exe = find_backend().ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::NotFound, "kali-backend.exe not found")
        })?;
        let work_dir = backend_exe.parent().unwrap_or(&backend_exe).to_path_buf();
        let instance_id = uuid::Uuid::new_v4().to_string();

        let mut command = Command::new(&backend_exe);
        command
            .current_dir(&work_dir)
            .env("KALI_HOST", BACKEND_HOST)
            .env("KALI_PORT", BACKEND_PORT)
            .env("KALI_CORS_ORIGINS", BACKEND_CORS_ORIGINS)
            .env("KALI_DESKTOP_INSTANCE_ID", &instance_id);
        let models_dir = work_dir.join("models");
        if models_dir.exists() {
            command.env("KALI_MODELS_DIR", &models_dir);
        }
        #[cfg(target_os = "windows")]
        command.creation_flags(CREATE_NO_WINDOW);
        match open_backend_logs(&runtime_data_dir().join("logs")) {
            Ok((stdout, stderr)) => {
                command
                    .stdout(Stdio::from(stdout))
                    .stderr(Stdio::from(stderr));
            }
            Err(err) => eprintln!("backend log open failed (non-fatal): {err}"),
        }
        let child = command.spawn()?;
        eprintln!(
            "spawned kali-backend PID {} instance {}",
            child.id(),
            instance_id
        );
        Ok(Spawned {
            handle: RealChild(child),
            instance_id,
        })
    }
}

/// Реальные часы.
struct RealClock;
impl startup::Clock for RealClock {
    fn now(&self) -> Instant {
        Instant::now()
    }
    fn sleep(&self, d: Duration) {
        std::thread::sleep(d);
    }
}

/// Записать новое состояние в `StartupCell` и эмитнуть на фронт (только смена).
fn publish_state(app: &AppHandle, s: StartupState) {
    let label = state_label(&s);
    if let Some(cell) = app.try_state::<StartupCell>() {
        *cell.label.lock().unwrap() = label.clone();
    }
    let _ = app.emit(STARTUP_EVENT, label);
}

/// Тело supervisor-потока: единственный owner Python-backend.
fn run_supervisor(
    app: AppHandle,
    bind_rx: Receiver<BindOutcome>,
    shutdown: Arc<AtomicBool>,
    waker: Arc<Waker>,
    ack_tx: Sender<()>,
) {
    let exe_present = find_backend().is_some();
    let mut ctx: SuperviseCtx<RealChild<Child>> = SuperviseCtx::new(exe_present);
    let probe = RealProbe::new();
    let mut spawner = RealSpawner;
    let clock = RealClock;
    loop {
        if ctx.rust_bound.is_none() {
            match bind_rx.try_recv() {
                Ok(o) => ctx.rust_bound = Some(o),
                // sender dropped без отправки = серв упал до bind → startup-fail.
                Err(TryRecvError::Disconnected) => {
                    ctx.rust_bound = Some(BindOutcome::StartupFailed)
                }
                Err(TryRecvError::Empty) => {}
            }
        }
        let ctrl = startup::supervise_step(
            &mut ctx,
            &probe,
            &mut spawner,
            &clock,
            &*shutdown,
            &mut |s| publish_state(&app, s),
        );
        if ctrl == LoopControl::Stop {
            break;
        }
        waker.wait(SUPERVISOR_TICK); // сон до тика или до shutdown (без busy-wait)
    }
    let _ = ack_tx.send(()); // ack: backend остановлен
}

/// Зарегистрировать глобальный шорткат (возвращает Result — вызывать fail-soft).
fn register_global_shortcut(app: &AppHandle) -> Result<(), tauri_plugin_global_shortcut::Error> {
    use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
    app.global_shortcut()
        .on_shortcut("CmdOrCtrl+Space", |handle: &AppHandle, _shortcut, event| {
            if event.state == ShortcutState::Pressed {
                if let Some(window) = handle.get_webview_window("main") {
                    if window.is_visible().unwrap_or(false) {
                        let _ = window.hide();
                    } else {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
        })
}

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "kali_desktop=info,tower_http=info".into()),
        )
        .init();

    let t0 = Instant::now();
    let shutdown = Arc::new(AtomicBool::new(false));
    let waker = Arc::new(Waker::new());
    let (ack_tx, ack_rx) = std::sync::mpsc::channel::<()>();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(StartupCell {
            label: Mutex::new(state_label(&StartupState::ShellReady)),
            t0,
            t_paint: Mutex::new(None),
        })
        .manage(ShutdownControl {
            flag: shutdown.clone(),
            waker: waker.clone(),
            ack: Mutex::new(Some(ack_rx)),
            done: AtomicBool::new(false),
        })
        .setup(move |app| {
            // Шорткат ПЕРВЫМ и fail-soft: сбой хоткея не должен абортить boot
            // (иначе после spawn потоков setup вернул бы Err и утёк бы поток).
            if let Err(e) = register_global_shortcut(app.handle()) {
                eprintln!("global shortcut registration failed (non-fatal): {e}");
            }
            // axum-поток ПЕРВЫМ; шлёт authoritative bind-результат.
            let (bind_tx, bind_rx) = std::sync::mpsc::channel::<BindOutcome>();
            std::thread::spawn(move || {
                let rt = tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .build()
                    .expect("build tokio runtime");
                if let Err(err) = rt.block_on(backend::serve_with_bind_signal(bind_tx)) {
                    eprintln!("Rust backend exited: {:#}", err);
                }
            });
            // supervisor-поток: единственный owner Python (spawn/health/backoff).
            let sup_app = app.handle().clone();
            std::thread::spawn(move || {
                run_supervisor(sup_app, bind_rx, shutdown, waker, ack_tx);
            });
            Ok(()) // после spawn — гарантированный Ok (нет fallible-хвоста)
        })
        .invoke_handler(tauri::generate_handler![greet, get_startup_state])
        .build(tauri::generate_context!())
        .expect("error while building KALI")
        .run(|app, event| match event {
            tauri::RunEvent::ExitRequested { api, .. } => {
                // Не выходить, пока cleanup не подтверждён реальным ack.
                match attempt_shutdown(&app.state::<ShutdownControl>(), SHUTDOWN_ACK_TIMEOUT) {
                    ShutdownResult::Completed => {}
                    ShutdownResult::Timeout | ShutdownResult::Disconnected => api.prevent_exit(),
                }
            }
            tauri::RunEvent::Exit => {
                let _ = attempt_shutdown(&app.state::<ShutdownControl>(), SHUTDOWN_ACK_TIMEOUT);
            }
            tauri::RunEvent::WindowEvent {
                event: tauri::WindowEvent::Destroyed,
                ..
            } => signal_shutdown_only(&app.state::<ShutdownControl>()),
            _ => {}
        });
}

#[cfg(test)]
mod tests;
