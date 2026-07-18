//! Тесты debug-only override пути бэкенда (`KALI_BACKEND_EXE`).
//!
//! Вынесены в модуль под `#[cfg(debug_assertions)]`: override отсутствует в
//! release-сборке, поэтому и тесты не должны там компилироваться.
//!
//! Контракт (tri-state, fail-closed):
//! * переменная не задана → `Unset` → используется канонический adjacent onedir;
//! * задана и валидна → `Valid` → используется override;
//! * задана, но пуста/невалидна → `Invalid` → `None`, **без отката** на adjacent
//!   (иначе опечатка в пути тихо подсунула бы другой артефакт).
//!
//! Валидность = абсолютный путь к файлу с именем `kali-backend.exe`, рядом с
//! которым лежит КАТАЛОГ `_internal`.
use super::*;
use std::ffi::OsStr;

fn ov(raw: &str, f: Vec<PathBuf>, d: Vec<PathBuf>) -> BackendOverride {
    resolve_backend_override(Some(OsStr::new(raw)), files(f), dirs(d))
}

fn exe() -> PathBuf {
    PathBuf::from("C:/custom/kali-backend/kali-backend.exe")
}
fn internal() -> PathBuf {
    PathBuf::from("C:/custom/kali-backend/_internal")
}

#[test]
fn override_unset_when_env_absent() {
    assert_eq!(
        resolve_backend_override(None, |_| true, |_| true),
        BackendOverride::Unset
    );
}

#[test]
fn override_accepts_absolute_onedir_exe() {
    assert_eq!(
        ov(
            "C:/custom/kali-backend/kali-backend.exe",
            vec![exe()],
            vec![internal()]
        ),
        BackendOverride::Valid(exe())
    );
}

#[test]
fn override_rejects_relative_path() {
    // Относительный путь зависит от cwd — ровно тот класс фоллбэка, что убран.
    assert_eq!(
        ov(
            "kali-backend/kali-backend.exe",
            vec![PathBuf::from("kali-backend/kali-backend.exe")],
            vec![PathBuf::from("kali-backend/_internal")]
        ),
        BackendOverride::Invalid
    );
}

#[test]
fn override_rejects_missing_exe() {
    assert_eq!(
        ov(
            "C:/custom/kali-backend/kali-backend.exe",
            vec![],
            vec![internal()]
        ),
        BackendOverride::Invalid
    );
}

#[test]
fn override_rejects_exe_without_sibling_internal() {
    // Плоский onefile по абсолютному пути не должен пролезать через override.
    assert_eq!(
        ov(
            "C:/custom/kali-backend.exe",
            vec![PathBuf::from("C:/custom/kali-backend.exe")],
            vec![]
        ),
        BackendOverride::Invalid
    );
}

#[test]
fn override_rejects_internal_that_is_a_file() {
    // `_internal` есть, но это файл, а не каталог → не валидный onedir.
    assert_eq!(
        ov(
            "C:/custom/kali-backend/kali-backend.exe",
            vec![exe(), internal()], // _internal среди ФАЙЛОВ
            vec![]
        ),
        BackendOverride::Invalid
    );
}

#[test]
fn override_rejects_wrong_exe_name() {
    // Указывать можно только на kali-backend.exe, даже если рядом есть _internal.
    let other = PathBuf::from("C:/custom/kali-backend/python.exe");
    assert_eq!(
        ov(
            "C:/custom/kali-backend/python.exe",
            vec![other],
            vec![internal()]
        ),
        BackendOverride::Invalid
    );
}

#[test]
fn override_blank_is_invalid_not_unset() {
    // Пустое значение — это заданная переменная с мусором, а НЕ «не задано».
    assert_eq!(ov("", vec![], vec![]), BackendOverride::Invalid);
    assert_eq!(ov("   ", vec![], vec![]), BackendOverride::Invalid);
}

// ── select_backend: невалидный override НЕ откатывается на adjacent ──────────

#[test]
fn select_invalid_override_does_not_fall_back_to_adjacent() {
    let adjacent = PathBuf::from("C:/app/kali-backend/kali-backend.exe");
    assert_eq!(
        select_backend(BackendOverride::Invalid, Some(adjacent)),
        None,
        "опечатка в KALI_BACKEND_EXE обязана падать, а не подсовывать другой артефакт"
    );
}

#[test]
fn select_unset_override_uses_adjacent() {
    let adjacent = PathBuf::from("C:/app/kali-backend/kali-backend.exe");
    assert_eq!(
        select_backend(BackendOverride::Unset, Some(adjacent.clone())),
        Some(adjacent)
    );
}

#[test]
fn select_valid_override_wins_over_adjacent() {
    let adjacent = PathBuf::from("C:/app/kali-backend/kali-backend.exe");
    assert_eq!(
        select_backend(BackendOverride::Valid(exe()), Some(adjacent)),
        Some(exe())
    );
}

#[test]
fn select_unset_without_adjacent_is_none() {
    assert_eq!(select_backend(BackendOverride::Unset, None), None);
}
