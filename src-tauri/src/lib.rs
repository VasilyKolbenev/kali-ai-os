use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

struct BackendProcess(Mutex<Option<Child>>);

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to KALI.", name)
}

#[tauri::command]
fn backend_status() -> String {
    match ureq::get("http://localhost:3005/health").call() {
        Ok(resp) if resp.status() == 200 => "running".to_string(),
        _ => "stopped".to_string(),
    }
}

fn find_backend() -> Option<PathBuf> {
    // Search in multiple locations for kali-backend.exe
    let candidates = [
        // 1. Next to this exe (installed mode)
        std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.join("kali-backend.exe"))),
        // 2. In dist/ (dev mode — built by PyInstaller)
        std::env::current_exe().ok().and_then(|p| {
            p.parent()
                .and_then(|d| d.parent()) // src-tauri/target/release -> src-tauri/target
                .and_then(|d| d.parent()) // -> src-tauri
                .and_then(|d| d.parent()) // -> project root
                .map(|root| root.join("dist").join("kali-backend.exe"))
        }),
        // 3. Current working directory
        Some(PathBuf::from("kali-backend.exe")),
        // 4. Program Files
        Some(PathBuf::from(r"C:\Program Files\KALI\kali-backend.exe")),
    ];

    for candidate in candidates.into_iter().flatten() {
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

fn start_backend(app: &AppHandle) {
    // First check if backend is already running
    if let Ok(resp) = ureq::get("http://localhost:3005/health").call() {
        if resp.status() == 200 {
            eprintln!("Backend already running on :3005");
            return;
        }
    }

    let backend_exe = match find_backend() {
        Some(path) => path,
        None => {
            eprintln!("kali-backend.exe not found. Start kernel manually: uv run python -m kernel.main");
            return;
        }
    };

    let work_dir = backend_exe.parent().unwrap_or(&backend_exe).to_path_buf();
    eprintln!("Starting backend: {:?}", backend_exe);

    match Command::new(&backend_exe).current_dir(&work_dir).spawn() {
        Ok(child) => {
            eprintln!("Started kali-backend (PID: {})", child.id());
            *app.state::<BackendProcess>().0.lock().unwrap() = Some(child);
        }
        Err(e) => eprintln!("Failed to start kali-backend: {}", e),
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
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            start_backend(app.handle());

            use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
            app.global_shortcut().on_shortcut(
                "CmdOrCtrl+Space",
                |handle: &AppHandle, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        if let Some(w) = handle.get_webview_window("main") {
                            if w.is_visible().unwrap_or(false) {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
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
