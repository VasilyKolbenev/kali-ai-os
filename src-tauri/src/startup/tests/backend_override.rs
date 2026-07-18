//! Тесты debug-only override пути бэкенда (`KALI_BACKEND_EXE`).
//!
//! Вынесены в модуль под `#[cfg(debug_assertions)]`: `resolve_backend_override`
//! отсутствует в release-сборке, поэтому и тесты не должны там компилироваться.
//!
//! Контракт: override принимается ТОЛЬКО если путь абсолютный, exe существует и
//! рядом с ним лежит каталог `_internal` (валидный PyInstaller onedir). Любое
//! нарушение → `None`, то есть падаем на канонический путь, а не на мусор.
use super::*;

fn exists_set(paths: Vec<PathBuf>) -> impl Fn(&Path) -> bool {
    move |x: &Path| paths.iter().any(|p| p == x)
}

#[test]
fn override_accepts_absolute_onedir_exe() {
    let exe = PathBuf::from("C:/custom/kali-backend/kali-backend.exe");
    let internal = PathBuf::from("C:/custom/kali-backend/_internal");
    let ok = exists_set(vec![exe.clone(), internal]);
    assert_eq!(
        resolve_backend_override(Some("C:/custom/kali-backend/kali-backend.exe"), ok),
        Some(exe)
    );
}

#[test]
fn override_rejects_relative_path() {
    // Относительный путь зависит от cwd — ровно тот класс фоллбэка, который убран.
    let ok = exists_set(vec![
        PathBuf::from("kali-backend/kali-backend.exe"),
        PathBuf::from("kali-backend/_internal"),
    ]);
    assert_eq!(
        resolve_backend_override(Some("kali-backend/kali-backend.exe"), ok),
        None
    );
}

#[test]
fn override_rejects_missing_exe() {
    let ok = exists_set(vec![PathBuf::from("C:/custom/kali-backend/_internal")]);
    assert_eq!(
        resolve_backend_override(Some("C:/custom/kali-backend/kali-backend.exe"), ok),
        None
    );
}

#[test]
fn override_rejects_exe_without_sibling_internal() {
    // Плоский onefile по абсолютному пути не должен пролезать через override.
    let exe = PathBuf::from("C:/custom/kali-backend.exe");
    let only_exe = exists_set(vec![exe]);
    assert_eq!(
        resolve_backend_override(Some("C:/custom/kali-backend.exe"), only_exe),
        None
    );
}

#[test]
fn override_absent_or_blank_is_none() {
    assert_eq!(resolve_backend_override(None, |_| true), None);
    assert_eq!(resolve_backend_override(Some(""), |_| true), None);
    assert_eq!(resolve_backend_override(Some("   "), |_| true), None);
}
