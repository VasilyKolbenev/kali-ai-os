//! Тесты канонического резолвера пути бэкенда (`resolve_backend_path`).
//!
//! Вынесены из `tests.rs` механическим переносом (тела тестов не менялись),
//! чтобы вернуть родительский файл под лимит 800 строк. Предикаты
//! `files()`/`dirs()` остаются в `tests.rs` — их разделяет модуль
//! `backend_override`.
use super::*;

fn app_dir() -> PathBuf {
    PathBuf::from("C:/app")
}
fn canonical_exe() -> PathBuf {
    app_dir().join("kali-backend").join("kali-backend.exe")
}
fn canonical_internal() -> PathBuf {
    app_dir().join("kali-backend").join("_internal")
}

#[test]
fn resolve_backend_accepts_adjacent_onedir() {
    let exe = canonical_exe();
    assert_eq!(
        resolve_backend_path(
            Some(&app_dir()),
            files(vec![exe.clone()]),
            dirs(vec![canonical_internal()])
        ),
        Some(exe)
    );
}

#[test]
fn resolve_backend_rejects_internal_that_is_a_file() {
    // `_internal` существует, но это ОБЫЧНЫЙ ФАЙЛ, а не каталог onedir-бандла.
    // Одного exists() здесь недостаточно — нужен именно is_dir.
    assert_eq!(
        resolve_backend_path(
            Some(&app_dir()),
            files(vec![canonical_exe(), canonical_internal()]), // _internal среди ФАЙЛОВ
            dirs(vec![])
        ),
        None
    );
}

#[test]
fn resolve_backend_rejects_exe_that_is_a_directory() {
    // `kali-backend.exe` существует как КАТАЛОГ — не исполняемый файл.
    assert_eq!(
        resolve_backend_path(
            Some(&app_dir()),
            files(vec![]),
            dirs(vec![canonical_exe(), canonical_internal()]) // exe среди КАТАЛОГОВ
        ),
        None
    );
}

#[test]
fn resolve_backend_rejects_onedir_without_internal() {
    assert_eq!(
        resolve_backend_path(Some(&app_dir()), files(vec![canonical_exe()]), dirs(vec![])),
        None
    );
}

#[test]
fn resolve_backend_ignores_flat_onefile_even_if_present() {
    // Плоский onefile рядом с desktop-exe больше НЕ кандидат: он порождает
    // внука-bootloader, переживающего Child.kill() и держащего порт.
    assert_eq!(
        resolve_backend_path(
            Some(&app_dir()),
            files(vec![app_dir().join("kali-backend.exe")]),
            dirs(vec![])
        ),
        None
    );
}

#[test]
fn resolve_backend_has_no_ancestor_or_cwd_fallback() {
    let dir = PathBuf::from("C:/app/target/debug");
    assert_eq!(
        resolve_backend_path(
            Some(&dir),
            files(vec![
                PathBuf::from("C:/app/dist/kali-backend.exe"),
                PathBuf::from("C:/app/dist/kali-backend/kali-backend.exe"),
                PathBuf::from("C:/app/target/kali-backend.exe"),
                PathBuf::from("kali-backend.exe"),
            ]),
            dirs(vec![PathBuf::from("C:/app/dist/kali-backend/_internal")])
        ),
        None
    );
}

#[test]
fn resolve_backend_missing_bundle_is_none() {
    assert_eq!(
        resolve_backend_path(Some(&app_dir()), files(vec![]), dirs(vec![])),
        None
    );
    // без exe_dir тоже None (никакого cwd-фоллбэка)
    assert_eq!(resolve_backend_path(None, |_| true, |_| true), None);
}
