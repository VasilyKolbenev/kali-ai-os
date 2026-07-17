pub mod backend;
mod startup;

use std::fs::{self, File, OpenOptions};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, Sender, TryRecvError};
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
/// Ограниченное ожидание ack при shutdown (bounded join).
const SHUTDOWN_ACK_TIMEOUT: Duration = Duration::from_secs(5);

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

/// Идемпотентный shutdown desktop-shell: флаг + Condvar-будильник + ack.
struct ShutdownControl {
    flag: Arc<AtomicBool>,
    waker: Arc<Waker>,
    ack: Mutex<Option<Receiver<()>>>,
    done: AtomicBool,
}

/// Condvar-будильник: supervisor спит на нём (без busy-wait), shutdown будит.
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
    /// Ждать до `dur` либо до пробуждения (shutdown).
    fn wait(&self, dur: Duration) {
        let guard = self.m.lock().unwrap();
        let _ = self.cv.wait_timeout(guard, dur);
    }
    fn wake(&self) {
        *self.m.lock().unwrap() = true;
        self.cv.notify_all();
    }
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

fn backend_http_agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_connect(Some(Duration::from_secs(1)))
        .timeout_send_request(Some(Duration::from_secs(1)))
        .build()
        .new_agent()
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

fn backend_log_files() -> std::io::Result<(File, File)> {
    let logs_dir = runtime_data_dir().join("logs");
    fs::create_dir_all(&logs_dir)?;
    let stdout = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(logs_dir.join("kali-backend.out.log"))?;
    let stderr = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(logs_dir.join("kali-backend.err.log"))?;
    Ok((stdout, stderr))
}

/// Путь backend через pure `resolve_backend_path` (реальная FS-проба).
fn find_backend() -> Option<PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));
    startup::resolve_backend_path(exe_dir.as_deref(), |p| p.exists())
}

// ── реальные адаптеры pure-трейтов ───────────────────────────────────────────

/// Обёртка над `std::process::Child`, реализующая `ChildHandle`.
struct RealChild(Child);

impl ChildHandle for RealChild {
    fn try_alive(&mut self) -> std::io::Result<bool> {
        // Some(status) = завершён (reaped); None = ещё жив.
        Ok(self.0.try_wait()?.is_none())
    }
    fn terminate_and_wait(&mut self) -> std::io::Result<()> {
        // Идемпотентно: kill уже завершённого возвращает Err — игнорируем;
        // wait реапит (в т.ч. уже завершённого возвращает кэш-статус).
        let _ = self.0.kill();
        self.0.wait()?; // wait — часть успешной termination
        Ok(())
    }
}

/// Отобразить HTTP-ответ :3005/health в `ProbeStatus` (ownership по instance-ID).
/// Чистая — юнит-тестируемая без сети.
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

/// Реальный HealthProbe: GET :3005/health, сверка `desktop_instance_id`.
struct RealProbe;

impl HealthProbe for RealProbe {
    fn status(&self, expected: Option<&str>) -> ProbeStatus {
        match backend_http_agent().get(BACKEND_HEALTH_URL).call() {
            Ok(mut resp) => {
                let code = resp.status().as_u16();
                let body = resp.body_mut().read_to_string().unwrap_or_default();
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
    type Handle = RealChild;
    fn spawn(&mut self) -> std::io::Result<Spawned<RealChild>> {
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
        if let Ok((stdout, stderr)) = backend_log_files() {
            command
                .stdout(Stdio::from(stdout))
                .stderr(Stdio::from(stderr));
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
    let mut ctx: SuperviseCtx<RealChild> = SuperviseCtx::new(exe_present);
    let probe = RealProbe;
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

/// Идемпотентный graceful shutdown: флаг + будильник + ограниченный ack.
fn trigger_shutdown(app: &AppHandle) {
    let ctl = app.state::<ShutdownControl>();
    if ctl.done.swap(true, Ordering::SeqCst) {
        return; // уже выполнено (ExitRequested → Exit → Destroyed идемпотентны)
    }
    ctl.flag.store(true, Ordering::SeqCst);
    ctl.waker.wake();
    let taken = ctl.ack.lock().unwrap().take();
    if let Some(ack) = taken {
        let _ = ack.recv_timeout(SHUTDOWN_ACK_TIMEOUT); // bounded join
    }
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
            // 1) axum-поток ПЕРВЫМ; шлёт authoritative bind-результат.
            let (bind_tx, bind_rx) = std::sync::mpsc::channel::<BindOutcome>();
            std::thread::spawn(move || {
                let rt = tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .build()
                    .expect("build tokio runtime");
                if let Err(err) = rt.block_on(backend::serve(bind_tx)) {
                    eprintln!("Rust backend exited: {:#}", err);
                }
            });

            // 2) supervisor-поток: единственный owner Python (spawn/health/backoff).
            let sup_app = app.handle().clone();
            std::thread::spawn(move || {
                run_supervisor(sup_app, bind_rx, shutdown, waker, ack_tx);
            });

            // 3) shortcut и НЕМЕДЛЕННЫЙ возврат — event loop сразу рисует webview.
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
            app.global_shortcut().on_shortcut(
                "CmdOrCtrl+Space",
                |handle: &AppHandle, _shortcut, event| {
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
                },
            )?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![greet, get_startup_state])
        .build(tauri::generate_context!())
        .expect("error while building KALI")
        .run(|app, event| match event {
            // ExitRequested/Exit идемпотентны; Destroyed — дополнительный сигнал.
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                trigger_shutdown(app);
            }
            tauri::RunEvent::WindowEvent {
                event: tauri::WindowEvent::Destroyed,
                ..
            } => trigger_shutdown(app),
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let body = r#"{"desktop_instance_id":"other"}"#;
        assert_eq!(
            classify_health(200, body, Some("id-1")),
            ProbeStatus::ForeignHealthy
        );
    }

    #[test]
    fn classify_health_missing_id_foreign() {
        let body = r#"{"status":"ok"}"#; // ручной запуск: id == null/absent
        assert_eq!(
            classify_health(200, body, Some("id-1")),
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

    #[test]
    fn real_child_lifecycle_try_alive_and_terminate() {
        // Живой процесс: ping loopback ~5с (кросс-платформенно завершится сам).
        #[cfg(target_os = "windows")]
        let mut c = Command::new("cmd");
        #[cfg(target_os = "windows")]
        c.args(["/c", "ping", "127.0.0.1", "-n", "10"]);
        #[cfg(not(target_os = "windows"))]
        let mut c = Command::new("sleep");
        #[cfg(not(target_os = "windows"))]
        c.arg("10");
        let child = c.spawn().expect("spawn test child");
        let mut rc = RealChild(child);
        assert!(rc.try_alive().unwrap(), "только что запущен → alive");
        rc.terminate_and_wait().expect("terminate живого");
        assert!(!rc.try_alive().unwrap(), "после terminate → not alive");
        // идемпотентность: повтор terminate уже завершённого — Ok, handle цел.
        rc.terminate_and_wait().expect("terminate идемпотентен");
    }
}
