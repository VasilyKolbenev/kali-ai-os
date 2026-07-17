pub mod backend;
// Вшивается в setup() в commit 2 (non-blocking boot); пока не подключён к рантайму.
#[allow(dead_code)]
mod startup;

use std::fs::{self, File, OpenOptions};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};

struct BackendProcess(Mutex<Option<Child>>);

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: &str = "3005";
const BACKEND_HEALTH_URL: &str = "http://127.0.0.1:3005/health";
const BACKEND_CORS_ORIGINS: &str = "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://localhost:1420,http://127.0.0.1:1420,http://localhost:1421,http://127.0.0.1:1421";
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to KALI.", name)
}

#[tauri::command]
fn backend_status() -> String {
    if backend_is_running() {
        "running".to_string()
    } else {
        "stopped".to_string()
    }
}

fn backend_http_agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_connect(Some(Duration::from_secs(1)))
        .timeout_send_request(Some(Duration::from_secs(1)))
        .build()
        .new_agent()
}

fn backend_is_running() -> bool {
    matches!(
        backend_http_agent().get(BACKEND_HEALTH_URL).call(),
        Ok(resp) if resp.status() == 200
    )
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

fn backend_log_files() -> std::io::Result<(File, File, PathBuf, PathBuf)> {
    let logs_dir = runtime_data_dir().join("logs");
    fs::create_dir_all(&logs_dir)?;

    let stdout_path = logs_dir.join("kali-backend.out.log");
    let stderr_path = logs_dir.join("kali-backend.err.log");
    let stdout = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&stdout_path)?;
    let stderr = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&stderr_path)?;

    Ok((stdout, stderr, stdout_path, stderr_path))
}

fn wait_for_backend_ready() -> bool {
    for _ in 0..20 {
        if backend_is_running() {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn find_backend() -> Option<PathBuf> {
    // exe_dir = directory containing kali-desktop.exe.
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));

    let candidates = [
        // Premium v3 install layout: kali-backend in its own subfolder next to
        // kali-desktop.exe (PyInstaller onedir bundle stays self-contained).
        exe_dir
            .as_ref()
            .map(|d| d.join("kali-backend").join("kali-backend.exe")),
        // Lite (NSIS) layout: backend flat next to kali-desktop.exe.
        exe_dir.as_ref().map(|d| d.join("kali-backend.exe")),
        // Dev mode: ../../../../dist/kali-backend.exe relative to cargo target.
        exe_dir.as_ref().and_then(|d| {
            d.parent()
                .and_then(|p| p.parent())
                .and_then(|p| p.parent())
                .map(|root| root.join("dist").join("kali-backend.exe"))
        }),
        // Last-resort PATH lookup.
        Some(PathBuf::from("kali-backend.exe")),
        // NOTE: removed the hardcoded C:\Program Files\KALI\ fallback from
        // earlier revisions — it pulled in stale residue from old dev installs
        // (Apr 17 backend pre-dating v1) and masked bugs in the real install
        // paths. If real paths break, fail loud rather than fall back to
        // whatever happens to sit in Program Files.
    ];

    candidates.into_iter().flatten().find(|p| p.exists())
}

fn start_backend(app: &AppHandle) {
    // Guard: check if we already hold a child process
    {
        let state = app.state::<BackendProcess>();
        let guard = state.0.lock().unwrap();
        if guard.is_some() {
            eprintln!("Backend child process already tracked, skipping spawn");
            return;
        }
    }

    if backend_is_running() {
        eprintln!(
            "Backend already running on {}:{}",
            BACKEND_HOST, BACKEND_PORT
        );
        return;
    }

    let backend_exe = match find_backend() {
        Some(path) => path,
        None => {
            eprintln!(
                "kali-backend.exe not found. Start kernel manually: uv run python -m kernel.main"
            );
            let _ = app.emit(
                "backend://failed",
                serde_json::json!({
                    "reason": "kali-backend.exe not found",
                    "log_path": runtime_data_dir().join("logs"),
                }),
            );
            return;
        }
    };

    let work_dir = backend_exe.parent().unwrap_or(&backend_exe).to_path_buf();
    let logs_dir = runtime_data_dir().join("logs");
    eprintln!("Starting backend (single instance): {:?}", backend_exe);

    let mut command = Command::new(&backend_exe);
    command
        .current_dir(&work_dir)
        .env("KALI_HOST", BACKEND_HOST)
        .env("KALI_PORT", BACKEND_PORT)
        .env("KALI_CORS_ORIGINS", BACKEND_CORS_ORIGINS);

    let models_dir = work_dir.join("models");
    if models_dir.exists() {
        command.env("KALI_MODELS_DIR", &models_dir);
    }

    #[cfg(target_os = "windows")]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match backend_log_files() {
        Ok((stdout, stderr, stdout_path, stderr_path)) => {
            eprintln!("Backend stdout log: {:?}", stdout_path);
            eprintln!("Backend stderr log: {:?}", stderr_path);
            command
                .stdout(Stdio::from(stdout))
                .stderr(Stdio::from(stderr));
        }
        Err(err) => eprintln!("Failed to prepare backend log files: {}", err),
    }

    match command.spawn() {
        Ok(child) => {
            eprintln!("Started kali-backend (PID: {})", child.id());
            *app.state::<BackendProcess>().0.lock().unwrap() = Some(child);
            if wait_for_backend_ready() {
                eprintln!("Backend is healthy on {}", BACKEND_HEALTH_URL);
            } else {
                eprintln!(
                    "Backend did not become healthy within 5s. Check logs in {:?}",
                    logs_dir
                );
                let _ = app.emit(
                    "backend://failed",
                    serde_json::json!({
                        "reason": "backend did not become healthy within 5s",
                        "log_path": logs_dir,
                    }),
                );
            }
        }
        Err(err) => {
            eprintln!("Failed to start kali-backend: {}", err);
            let _ = app.emit(
                "backend://failed",
                serde_json::json!({
                    "reason": format!("failed to spawn backend: {err}"),
                    "log_path": logs_dir,
                }),
            );
        }
    }
}

fn stop_backend(app: &AppHandle) {
    let state = app.state::<BackendProcess>();
    let mut guard = state.0.lock().unwrap();
    if let Some(ref mut child) = *guard {
        eprintln!("Stopping kali-backend (PID: {})", child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
    *guard = None;
}

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "kali_desktop=info,tower_http=info".into()),
        )
        .init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            start_backend(app.handle());

            // Phase 0: start Rust axum server on 127.0.0.1:3006 alongside Python
            std::thread::spawn(|| {
                let rt = tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .build()
                    .expect("build tokio runtime");
                if let Err(err) = rt.block_on(backend::serve()) {
                    eprintln!("Rust backend exited: {:#}", err);
                }
            });

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
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                stop_backend(window.app_handle());
            }
        })
        .invoke_handler(tauri::generate_handler![greet, backend_status])
        .run(tauri::generate_context!())
        .expect("error while running KALI");
}
