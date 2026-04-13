use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

/// Backend process handle — killed on app exit.
struct BackendProcess(Mutex<Option<Child>>);

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to KALI.", name)
}

#[tauri::command]
fn backend_status() -> String {
    // Quick health check
    match ureq::get("http://localhost:3005/health").call() {
        Ok(resp) => {
            if resp.status() == 200 {
                "running".to_string()
            } else {
                "error".to_string()
            }
        }
        Err(_) => "stopped".to_string(),
    }
}

fn start_backend(app: &AppHandle) {
    // Look for kali-backend.exe next to the app executable
    let app_dir = app
        .path()
        .resource_dir()
        .unwrap_or_else(|_| std::env::current_exe().unwrap().parent().unwrap().to_path_buf());

    let backend_exe = app_dir.join("kali-backend.exe");

    if !backend_exe.exists() {
        // Dev mode: try running via Python directly
        eprintln!("kali-backend.exe not found at {:?}, skipping auto-start", backend_exe);
        eprintln!("In dev mode, start the kernel manually: uv run python -m kernel.main");
        return;
    }

    match Command::new(&backend_exe)
        .current_dir(&app_dir)
        .spawn()
    {
        Ok(child) => {
            eprintln!("Started kali-backend (PID: {})", child.id());
            let state = app.state::<BackendProcess>();
            *state.0.lock().unwrap() = Some(child);
        }
        Err(e) => {
            eprintln!("Failed to start kali-backend: {}", e);
        }
    }
}

fn stop_backend(app: &AppHandle) {
    let state = app.state::<BackendProcess>();
    if let Some(mut child) = state.0.lock().unwrap().take() {
        eprintln!("Stopping kali-backend (PID: {})", child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            // Start backend process
            start_backend(app.handle());

            // Register Ctrl+Space global shortcut
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

            app.global_shortcut().on_shortcut(
                "CmdOrCtrl+Space",
                |app_handle: &AppHandle, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let visible = window.is_visible().unwrap_or(false);
                            if visible {
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
        .on_window_event(|app, event| {
            // Stop backend when app closes
            if let tauri::WindowEvent::Destroyed = event {
                stop_backend(app);
            }
        })
        .invoke_handler(tauri::generate_handler![greet, backend_status])
        .run(tauri::generate_context!())
        .expect("error while running KALI");
}
