# Crash opt-in (Windows) — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При смерти Python-backend предложить пользователю (opt-in) собрать **отредактированный** отчёт о сбое в локальный .txt, который он сам передаёт разработчику.

**Architecture:** Всё ядро — `src-tauri/src/backend/crash.rs` (редактор логов, сборщик отчёта, проб Python-liveness, reveal). Транспорт — 3 **stateless** HTTP-роута на существующем axum control-plane :3006 (`/crash/status|report|reveal`), аппендятся в `router_full` как `/updater/*` (Extension НЕ нужен). UI — хук `useBackendLiveness` (поллит `/crash/status`, дебаунс 3 подряд) + компонент `CrashReportPrompt`, монтируется рядом с существующим `kernelStage`-оверлеем в App.tsx.

**Tech Stack:** Rust (regex, reqwest, chrono, dirs, axum, tokio), React 19 + vitest.

**Spec:** `docs/superpowers/specs/2026-07-14-crash-optin-design.md` — **прочитать ПЕРЕД началом** (там таблица точных regex и обоснования).

**Гейты:** `cd src-tauri; cargo test --test crash_redact --test crash_report --test crash_probe --test crash_routes` · `cargo check --lib` · `cd ui; pnpm exec vitest run` · полный прогон перед пушем.

> **Binding-ограничения Vasily:** (1) **без хардкода** — пороги/паттерны = именованные константы, пути через `dirs::data_dir()`, URL Python через существующий `proxy::python_backend_url()` (env-переопределяем); (2) **ничего не ломать** — только аддитивно; существующие роуты/баннер/WS не трогать; все текущие тесты остаются зелёными.

> **ГОТЧА (Windows Installer Detection):** имена `crash_*` НЕ содержат триггеров (install/setup/update/patch) → error 740 не грозит. Если внезапно всплывёт — тот же обход, что у updater: `$env:__COMPAT_LAYER='RunAsInvoker'`.

---

## Chunk 1: Rust — редактор и отчёт

### Task 1: `redact()` — редактор логов (safety-critical)

**Files:**
- Modify: `src-tauri/Cargo.toml` (dep `regex`)
- Create: `src-tauri/src/backend/crash.rs`
- Modify: `src-tauri/src/backend/mod.rs` (`pub mod crash;` — алфавитно, между `auth` и `event_bus`; посмотреть фактический список)
- Test: `src-tauri/tests/crash_redact.rs`

- [ ] **Step 1: Добавить зависимость**

В `[dependencies]` `src-tauri/Cargo.toml`:

```toml
# crash-репорт: редакция секретов в логах перед показом/передачей.
regex = "1"
```

- [ ] **Step 2: Написать падающие тесты**

`src-tauri/tests/crash_redact.rs`:

```rust
//! Редактор crash-логов. Позитивы по классам 1-6 + анти-false-positive.
//! Спека: docs/superpowers/specs/2026-07-14-crash-optin-design.md §Редакция
use kali_desktop::backend::crash::redact;

const MASK: &str = "***REDACTED***";

// ── Класс 1: ключи с префиксом ──────────────────────────────────
#[test]
fn masks_openai_and_anthropic_keys() {
    let out = redact("using key sk-abcdefghijklmnopqrstuvwxyz012345 now");
    assert!(out.contains(MASK), "out={out}");
    assert!(!out.contains("abcdefghijklmnop"), "ключ утёк: {out}");

    let out = redact("key=sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789");
    assert!(!out.contains("AbCdEfGhIjKl"), "ключ утёк: {out}");
}

#[test]
fn masks_google_and_jwt() {
    let out = redact("goog AIzaSyA1234567890123456789012345678901234 tail");
    assert!(!out.contains("AIzaSyA1234567890"), "ключ утёк: {out}");
    assert!(out.contains("tail"), "съело хвост строки: {out}");

    let jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123";
    let out = redact(&format!("Auth token {jwt} end"));
    assert!(!out.contains("eyJzdWIiOiIxMjM0"), "JWT утёк: {out}");
    assert!(out.contains("end"), "съело хвост: {out}");
}

// ── Класс 2: Bearer / Authorization ─────────────────────────────
#[test]
fn masks_bearer_and_authorization() {
    let out = redact("hdr: Bearer abc.def-ghi_jkl123");
    assert!(!out.contains("abc.def-ghi"), "токен утёк: {out}");

    let out = redact("Authorization: Basic dXNlcjpwYXNz");
    assert!(!out.contains("dXNlcjpwYXNz"), "basic утёк: {out}");
}

// ── Класс 3: assignment (=) и conn-string ───────────────────────
#[test]
fn masks_assignment_with_and_without_quotes() {
    let out = redact("api_key=hunter2secret");
    assert!(!out.contains("hunter2secret"), "утекло: {out}");
    assert!(out.contains("api_key="), "имя ключа должно остаться: {out}");

    let out = redact(r#"password="hunter2secret""#);
    assert!(!out.contains("hunter2secret"), "утекло из кавычек: {out}");

    let out = redact("password=hunter2");   // 7 символов ≥ порога 6
    assert!(!out.contains("hunter2"), "короткий пароль утёк: {out}");
}

#[test]
fn masks_connection_string_password() {
    let out = redact("postgres://user:s3cr3tpass@host:5432/db");
    assert!(!out.contains("s3cr3tpass"), "пароль утёк: {out}");
    assert!(out.contains("user"), "юзер должен остаться (диагностика): {out}");

    // userless и +-схемы
    let out = redact("redis://:mypassword123@localhost:6379");
    assert!(!out.contains("mypassword123"), "userless пароль утёк: {out}");
    let out = redact("mongodb+srv://u:p4ssw0rdX@cluster.example.net");
    assert!(!out.contains("p4ssw0rdX"), "+srv пароль утёк: {out}");
}

// ── Класс 4: длинные руны ───────────────────────────────────────
#[test]
fn masks_long_hex_and_base64_runes() {
    // 64-hex = формат control-plane токена
    let out = redact("token 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    assert!(out.contains(MASK), "64-hex не замаскирован: {out}");

    let b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVm";
    let out = redact(&format!("blob {b64}"));
    assert!(out.contains(MASK), "base64-руна не замаскирована: {out}");
}

// ── Класс 5-6: email и Windows-путь ─────────────────────────────
#[test]
fn masks_email_and_windows_user_path() {
    let out = redact("user vasily.k+test@example.com wrote");
    assert!(!out.contains("vasily.k+test@example.com"), "email утёк: {out}");
    assert!(out.contains("wrote"), "съело хвост: {out}");

    let out = redact(r"loading C:\Users\Vasily\AppData\Roaming\KALI\config.yaml");
    assert!(!out.contains("Vasily"), "username утёк: {out}");
    assert!(out.contains("<user>"), "нет плейсхолдера: {out}");
    assert!(out.contains("AppData"), "съело остаток пути: {out}");

    // forward-slash форма
    let out = redact("path C:/Users/Vasily/models");
    assert!(!out.contains("Vasily"), "username утёк (slash): {out}");
}

// ── Анти-false-positive: обычный текст НЕ трогаем ───────────────
#[test]
fn does_not_mask_ordinary_words_and_paths() {
    for input in [
        "disk cache warmed in 12ms",
        "task exception was never retrieved",
        "desktop shell ready",
        "flask is not installed",
        "token count: 512",                       // двоеточие, не '=' → не assignment
        r"loading C:\Program Files\KALI\models",  // не \users\
        "whisper device=cuda float16",            // device= не в списке ключей
    ] {
        assert_eq!(redact(input), input, "ложное срабатывание на: {input}");
    }
}

#[test]
fn redaction_is_idempotent() {
    let once = redact("api_key=hunter2secret and sk-abcdefghijklmnopqrstuvwxyz012345");
    assert_eq!(redact(&once), once, "повторная редакция меняет текст");
}

// ── Комбо: все классы в одном тексте (спека §Тесты) ─────────────
#[test]
fn masks_all_classes_in_one_blob() {
    let input = concat!(
        "Traceback (most recent call last)\n",
        "  loading C:\\Users\\Vasily\\AppData\\KALI\\config.yaml\n",
        "  api_key=hunter2secret\n",
        "  sk-abcdefghijklmnopqrstuvwxyz012345\n",
        "  Authorization: Basic dXNlcjpwYXNz\n",
        "  Bearer abc.def-ghi_jkl123\n",
        "  postgres://user:s3cr3tpass@host:5432/db\n",
        "  contact vasily@example.com\n",
        "  0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n",
        "RuntimeError: boom\n",
    );
    let out = redact(input);
    for secret in [
        "Vasily",
        "hunter2secret",
        "abcdefghijklmnopqrstuvwxyz012345",
        "dXNlcjpwYXNz",
        "abc.def-ghi_jkl123",
        "s3cr3tpass",
        "vasily@example.com",
    ] {
        assert!(!out.contains(secret), "утекло {secret:?} в комбо:\n{out}");
    }
    // диагностика выживает
    assert!(out.contains("Traceback"), "съело диагностику:\n{out}");
    assert!(out.contains("RuntimeError: boom"), "съело причину:\n{out}");
    assert!(out.contains("AppData"), "съело остаток пути:\n{out}");
}
```

- [ ] **Step 3: Запустить — убедиться, что падают**

Run: `cd src-tauri; cargo test --test crash_redact`
Expected: FAIL — `unresolved import kali_desktop::backend::crash`.

- [ ] **Step 4: Реализация**

`src-tauri/src/backend/crash.rs` (начало файла; остальное добавят Task 2-3):

```rust
//! Crash opt-in: редакция логов, сборка отчёта, проб liveness, reveal.
//!
//! Спека: docs/superpowers/specs/2026-07-14-crash-optin-design.md
//! Сток ЛОКАЛЬНЫЙ — отчёт пишется в файл, пользователь передаёт его сам.
//! Ничего не собирается и не отправляется без явного клика.

use std::sync::LazyLock;

use regex::Regex;

/// Плейсхолдер вместо секрета. Не матчится ни одним паттерном ниже —
/// поэтому `redact()` идемпотентна.
const MASK: &str = "***REDACTED***";

// ── Паттерны (порядок применения = порядок объявления) ───────────
// Сначала специфичные ключи, потом руны, потом email/пути: иначе
// маскировка пути могла бы съесть токен раньше времени.

/// OpenAI/Anthropic/DeepSeek. `\b` + длина {20,} — чтобы `disk-`/`task-`
/// не ловились (между буквой и `s` нет границы слова).
static RE_KEY_SK: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\bsk-(ant-|proj-)?[A-Za-z0-9_-]{20,}\b").unwrap());
/// Google API key — фиксированная длина 35 после префикса.
static RE_KEY_GOOGLE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\bAIza[0-9A-Za-z_-]{35}\b").unwrap());
/// JWT — base64url (`-`/`_`), НЕ ловится base64-руной ниже.
static RE_JWT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*").unwrap()
});
static RE_BEARER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+").unwrap());
/// **`.+`, НЕ `\S+`:** `\S+` съел бы только `Authorization: Basic`, оставив сам
/// credential (`Basic dXNlcjpwYXNz` — 12 символов, ниже порога base64-руны, то
/// есть дальше его никто не поймает = утечка). `.` не матчит `\n`, поэтому
/// маскируется ровно значение заголовка, следующие строки лога целы.
static RE_AUTHORIZATION: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)\bauthorization:\s*.+").unwrap());
/// Только `=` (не `:`): `token count: 512` в прозе маскировать не нужно.
/// Опциональная кавычка + минимум 6 символов значения.
static RE_ASSIGN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\s*=\s*["']?[^\s"']{6,}"#)
        .unwrap()
});
/// `scheme://user:pass@` → пароль срезаем, юзера оставляем (диагностика).
/// Схема допускает `+.-` (mongodb+srv), юзер может быть пустым (redis://:pass@).
static RE_CONN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)\b([a-z][a-z0-9+.-]*)://([^:@\s]*):[^@\s]+@").unwrap());
/// Формат control-plane токена (64 hex) попадает сюда.
static RE_HEX_RUN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[0-9a-fA-F]{32,}\b").unwrap());
static RE_B64_RUN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[A-Za-z0-9+/]{40,}={0,2}\b").unwrap());
static RE_EMAIL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b").unwrap());
/// `C:\Users\<имя>` и `C:/Users/<имя>` — маскируем только сегмент имени.
///
/// Отступление от спеки (осознанное): `%USERPROFILE%` НЕ маскируем — это
/// литеральный плейсхолдер, имени пользователя он не содержит; маскировать
/// нечего. Если лог печатает РАСКРЫТЫЙ путь — его ловит этот же паттерн.
static RE_WIN_USER_PATH: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)([a-z]:[\\/]users[\\/])[^\\/\s]+").unwrap());

/// Замаскировать секреты в тексте лога.
///
/// Консервативно: лучше пере-замаскировать, чем пропустить. Приемлемый
/// over-mask (документирован в спеке): 40-hex git-SHA и длинные base64-блобы
/// попадают под руны — это безопаснее, чем пропустить ключ.
///
/// НЕ гарантия: редакция — defense-in-depth. Финальные предохранители —
/// читаемый .txt (юзер видит, что отправляет) и локальный сток.
pub fn redact(input: &str) -> String {
    let s = RE_KEY_SK.replace_all(input, MASK);
    let s = RE_KEY_GOOGLE.replace_all(&s, MASK);
    let s = RE_JWT.replace_all(&s, MASK);
    let s = RE_BEARER.replace_all(&s, format!("Bearer {MASK}").as_str());
    let s = RE_AUTHORIZATION.replace_all(&s, format!("Authorization: {MASK}").as_str());
    let s = RE_ASSIGN.replace_all(&s, format!("${{1}}={MASK}").as_str());
    let s = RE_CONN.replace_all(&s, "${1}://${2}:***@");
    let s = RE_HEX_RUN.replace_all(&s, MASK);
    let s = RE_B64_RUN.replace_all(&s, MASK);
    let s = RE_EMAIL.replace_all(&s, "***@***");
    let s = RE_WIN_USER_PATH.replace_all(&s, "${1}<user>");
    s.into_owned()
}
```

В `src-tauri/src/backend/mod.rs` добавить `pub mod crash;` в алфавитную позицию (посмотреть фактический список — ожидаемо между `auth` и `event_bus`).

**Замечание реализатору:** `std::sync::LazyLock` стабилен с Rust 1.80. Если тулчейн старше и компиляция упадёт — добавь `once_cell = "1"` и используй `once_cell::sync::Lazy` (поведение идентично). Отметь замену в отчёте.

- [ ] **Step 5: Прогнать тесты**

Run: `cd src-tauri; cargo test --test crash_redact`
Expected: PASS (10 тестов).

- [ ] **Step 6: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/backend/crash.rs src-tauri/src/backend/mod.rs src-tauri/tests/crash_redact.rs
git commit -m "feat(crash): log redactor with anchored secret patterns"
```

### Task 2: `crash_paths()` + `build_report()`

**Files:**
- Modify: `src-tauri/src/backend/crash.rs`
- Test: `src-tauri/tests/crash_report.rs`

- [ ] **Step 1: Падающие тесты**

`src-tauri/tests/crash_report.rs`:

```rust
//! Сборка отчёта: хвост логов, фолбэк без логов, бюджет байтов, редакция.
use kali_desktop::backend::crash::{build_report, CrashMeta, CRASH_LOG_FILES};

fn meta() -> CrashMeta {
    CrashMeta {
        version: "1.0.0-rc1",
        os: "windows",
        arch: "x86_64",
        ts: "2026-07-14T16:40:00Z".to_string(),
        reason: Some("backend did not become healthy within 5s".to_string()),
    }
}

#[test]
fn builds_report_with_meta_and_redacted_tails() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("logs");
    let reports = tmp.path().join("crash-reports");
    std::fs::create_dir_all(&logs).unwrap();
    std::fs::write(
        logs.join(CRASH_LOG_FILES[0]), // err
        "Traceback (most recent call last)\nRuntimeError: boom\n",
    )
    .unwrap();
    std::fs::write(
        logs.join(CRASH_LOG_FILES[1]), // out
        "loading C:\\Users\\Vasily\\models\napi_key=hunter2secret\n",
    )
    .unwrap();

    let rep = build_report(&logs, &reports, &meta()).unwrap();

    // мета
    assert!(rep.text.contains("1.0.0-rc1"));
    assert!(rep.text.contains("windows"));
    assert!(rep.text.contains("backend did not become healthy"));
    // содержимое обоих логов
    assert!(rep.text.contains("RuntimeError: boom"));
    // редакция применена к телу
    assert!(!rep.text.contains("Vasily"), "username утёк в отчёт");
    assert!(!rep.text.contains("hunter2secret"), "ключ утёк в отчёт");
    // err-секция идёт ПЕРЕД out-секцией (там трейсбеки — главная диагностика)
    let i_err = rep.text.find(CRASH_LOG_FILES[0]).unwrap();
    let i_out = rep.text.find(CRASH_LOG_FILES[1]).unwrap();
    assert!(i_err < i_out, "err-секция должна быть первой");
    // файл записан, содержимое совпадает с возвращённым текстом
    assert!(rep.path.exists());
    assert_eq!(std::fs::read_to_string(&rep.path).unwrap(), rep.text);
    // имя файла без ':' — иначе Windows не запишет
    let name = rep.path.file_name().unwrap().to_string_lossy().into_owned();
    assert!(!name.contains(':'), "двоеточие в имени файла: {name}");
    assert!(name.starts_with("crash-") && name.ends_with(".txt"), "имя: {name}");
}

#[test]
fn missing_logs_produce_meta_only_report_not_an_error() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("nope");      // не существует
    let reports = tmp.path().join("crash-reports");
    let rep = build_report(&logs, &reports, &meta()).unwrap();
    assert!(rep.text.contains("1.0.0-rc1"), "мета должна быть");
    assert!(rep.text.contains("логи не найдены"), "нет честной пометки: {}", rep.text);
    assert!(rep.path.exists());
}

#[test]
fn keeps_only_recent_lines_via_tail() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("logs");
    let reports = tmp.path().join("crash-reports");
    std::fs::create_dir_all(&logs).unwrap();
    // много КОРОТКИХ строк: сработает только line-tail (байтовый бюджет не задет)
    let body: String = (0..5000).map(|i| format!("line-{i}\n")).collect();
    std::fs::write(logs.join(CRASH_LOG_FILES[0]), &body).unwrap();

    let rep = build_report(&logs, &reports, &meta()).unwrap();
    assert!(rep.text.contains("line-4999"), "свежий хвост потерян");
    assert!(!rep.text.contains("line-0\n"), "старая строка не отброшена");
}

/// Байтовый бюджет: 400 ДЛИННЫХ строк (~160 KB) переживают line-tail
/// (их ровно CRASH_LOG_TAIL_LINES), но превышают per-file бюджет (~127 KB) —
/// значит режет именно `clamp_tail`. Без этого теста clamp не исполняется НИ РАЗУ.
#[test]
fn byte_budget_truncates_older_edge_and_marks_it() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("logs");
    let reports = tmp.path().join("crash-reports");
    std::fs::create_dir_all(&logs).unwrap();
    // ПАД С ПРОБЕЛАМИ, НЕ "x".repeat(380): сплошная alnum-руна ≥40 символов
    // попала бы под RE_B64_RUN и схлопнулась в 14 байт (redact идёт ДО clamp) —
    // хвост стал бы ~9 KB, бюджет не превысился, clamp снова не исполнился бы.
    // Руны по 4 символа редактор не трогает. Не «упрощать» обратно.
    let pad = "xxxx ".repeat(76); // 380 байт, redact-нейтрально
    let body: String = (0..kali_desktop::backend::crash::CRASH_LOG_TAIL_LINES)
        .map(|i| format!("line-{i}-{pad}\n"))
        .collect();
    assert!(body.len() > 150_000, "фикстура мала — clamp не сработает");
    std::fs::write(logs.join(CRASH_LOG_FILES[0]), &body).unwrap();

    let rep = build_report(&logs, &reports, &meta()).unwrap();
    assert!(rep.text.contains("обрезано"), "нет маркера обрезки:\n{}", &rep.text[..200]);
    assert!(rep.text.contains("line-399-"), "свежий хвост потерян (обрезали не тот край)");
    assert!(!rep.text.contains("line-0-"), "старый край не обрезан");
    assert!(
        rep.text.len() <= kali_desktop::backend::crash::CRASH_REPORT_MAX_BYTES,
        "отчёт {} > предела",
        rep.text.len()
    );
}

#[test]
fn empty_log_file_is_handled() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("logs");
    let reports = tmp.path().join("crash-reports");
    std::fs::create_dir_all(&logs).unwrap();
    std::fs::write(logs.join(CRASH_LOG_FILES[0]), "").unwrap();
    let rep = build_report(&logs, &reports, &meta()).unwrap();
    assert!(rep.path.exists());
    assert!(rep.text.contains("1.0.0-rc1"));
}
```

- [ ] **Step 2: Запустить — падают** (`cargo test --test crash_report` → compile error)

- [ ] **Step 3: Реализация в `crash.rs`**

```rust
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

/// Сколько последних строк каждого лога берём.
pub const CRASH_LOG_TAIL_LINES: usize = 400;
/// Жёсткий предел итогового отчёта.
pub const CRASH_REPORT_MAX_BYTES: usize = 256 * 1024;
/// Сколько байт с конца файла сканируем ради хвоста (лог может быть огромным —
/// целиком в память не читаем).
const CRASH_TAIL_SCAN_BYTES: u64 = 1024 * 1024;
const CRASH_TRUNCATED_MARKER: &str = "…(обрезано)";
/// **err первым** — там трейсбеки/паники (главная диагностика);
/// out засоряется /health-поллингом (см. спеку §Шум поллинга).
pub const CRASH_LOG_FILES: [&str; 2] = ["kali-backend.err.log", "kali-backend.out.log"];

/// Мета отчёта. `version`/`os`/`arch` — `'static` из compile-time констант.
pub struct CrashMeta {
    pub version: &'static str,
    pub os: &'static str,
    pub arch: &'static str,
    pub ts: String,
    pub reason: Option<String>,
}

pub struct CrashReport {
    pub path: PathBuf,
    pub text: String,
}

/// `(logs_dir, reports_dir)`.
///
/// `runtime_data_dir()` из lib.rs (бинарь-крейт) отсюда не видна, поэтому
/// резолвим сами. **`data_dir()` = `%APPDATA%` (roaming)** — туда пишет логи
/// lib.rs. НЕ `data_local_dir()`: это `%LOCALAPPDATA%`, куда смотрит
/// `updater::updates_dir()` — скопировать его сюда = читать не ту папку.
pub fn crash_paths() -> Result<(PathBuf, PathBuf)> {
    let base = dirs::data_dir()
        .context("не удалось определить папку данных пользователя")?
        .join("KALI");
    Ok((base.join("logs"), base.join("crash-reports")))
}

/// Последние `n` строк файла, читая максимум `CRASH_TAIL_SCAN_BYTES` с конца.
/// `None` — файла нет/не читается.
fn tail_lines(path: &Path, n: usize) -> Option<String> {
    let mut file = std::fs::File::open(path).ok()?;
    let len = file.metadata().ok()?.len();
    let start = len.saturating_sub(CRASH_TAIL_SCAN_BYTES);
    file.seek(SeekFrom::Start(start)).ok()?;
    let mut buf = Vec::new();
    file.read_to_end(&mut buf).ok()?;
    let text = String::from_utf8_lossy(&buf);
    let lines: Vec<&str> = text.lines().collect();
    let from = lines.len().saturating_sub(n);
    Some(lines[from..].join("\n"))
}

/// Обрезать секцию до `budget` байт, СОХРАНЯЯ свежий хвост (режем старший край).
fn clamp_tail(section: &str, budget: usize) -> String {
    if section.len() <= budget {
        return section.to_string();
    }
    let cut = section.len() - budget.saturating_sub(CRASH_TRUNCATED_MARKER.len() + 1);
    // не рвём UTF-8: сдвигаемся вперёд до границы символа
    let mut idx = cut.min(section.len());
    while idx < section.len() && !section.is_char_boundary(idx) {
        idx += 1;
    }
    format!("{CRASH_TRUNCATED_MARKER}\n{}", &section[idx..])
}

/// Собрать отчёт: мета + отредактированные хвосты логов → файл в `reports_dir`.
///
/// Бюджет байт делится ПОРОВНУ между логами, а не режется общим краем:
/// иначе шумный `out` мог бы вытеснить `err` с трейсбеком.
pub fn build_report(logs_dir: &Path, reports_dir: &Path, meta: &CrashMeta) -> Result<CrashReport> {
    let mut report = format!(
        "KALI crash report\nversion: {}\nos: {} / {}\ntime: {}\nreason: {}\n",
        meta.version,
        meta.os,
        meta.arch,
        meta.ts,
        meta.reason.as_deref().unwrap_or("-"),
    );

    // Считается ДО дописывания секций (по длине одной шапки) — не двигать вниз.
    let per_file_budget = CRASH_REPORT_MAX_BYTES
        .saturating_sub(report.len())
        .saturating_sub(512) // запас под заголовки секций
        / CRASH_LOG_FILES.len();

    let mut any_log = false;
    for name in CRASH_LOG_FILES {
        match tail_lines(&logs_dir.join(name), CRASH_LOG_TAIL_LINES) {
            Some(tail) => {
                any_log = true;
                let redacted = redact(&tail);
                report.push_str(&format!(
                    "\n--- {name} (последние {CRASH_LOG_TAIL_LINES} строк, отредактировано) ---\n{}\n",
                    clamp_tail(&redacted, per_file_budget)
                ));
            }
            None => report.push_str(&format!("\n--- {name}: логи не найдены ---\n")),
        }
    }
    if !any_log {
        report.push_str("\n(логи не найдены — отчёт содержит только мету)\n");
    }

    std::fs::create_dir_all(reports_dir)
        .with_context(|| format!("создать {}", reports_dir.display()))?;
    // Имя файла — только цифры из ts (YYYYMMDDhhmmss): двоеточие Windows не
    // примет, а rfc3339 тащит дробные секунды и смещение. Два краша в одну
    // секунду перезапишут друг друга — приемлемо (юзер шлёт отчёт сразу).
    let stamp: String = meta.ts.chars().filter(|c| c.is_ascii_digit()).take(14).collect();
    let path = reports_dir.join(format!("crash-{stamp}.txt"));
    std::fs::write(&path, &report).with_context(|| format!("записать {}", path.display()))?;
    Ok(CrashReport { path, text: report })
}
```

- [ ] **Step 4: Прогнать** — `cargo test --test crash_report` PASS (4), `--test crash_redact` не сломан.

- [ ] **Step 5: Commit** — `feat(crash): report builder with per-file byte budget and redacted tails`

### Task 3: `probe_backend_alive()` + `reveal_reports_dir()`

**Files:**
- Modify: `src-tauri/src/backend/crash.rs`
- Test: `src-tauri/tests/crash_probe.rs`

- [ ] **Step 1: Падающие тесты**

`src-tauri/tests/crash_probe.rs`:

```rust
//! Проб Python-liveness. КЛЮЧЕВОЕ: зависший Python не должен вешать хендлер —
//! у проба СВОЙ таймаут (proxy::proxy_get_json таймаута НЕ имеет).
use std::net::SocketAddr;
use std::time::{Duration, Instant};

use axum::{routing::get, Router};
use kali_desktop::backend::crash::probe_backend_alive_with;

async fn spawn_health(alive: bool, hang: bool) -> String {
    let app = Router::new().route(
        "/health",
        get(move || async move {
            if hang {
                // «завис»: принял соединение, но не отвечает
                tokio::time::sleep(Duration::from_secs(30)).await;
            }
            if alive {
                (axum::http::StatusCode::OK, "ok")
            } else {
                (axum::http::StatusCode::INTERNAL_SERVER_ERROR, "down")
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{addr}")
}

#[tokio::test]
async fn alive_backend_reports_true() {
    let base = spawn_health(true, false).await;
    assert!(probe_backend_alive_with(&base, Duration::from_secs(2)).await);
}

#[tokio::test]
async fn non_success_status_reports_false() {
    let base = spawn_health(false, false).await;
    assert!(!probe_backend_alive_with(&base, Duration::from_secs(2)).await);
}

#[tokio::test]
async fn dead_port_reports_false_fast() {
    // на этот порт никто не слушает → connection refused
    let started = Instant::now();
    let alive = probe_backend_alive_with("http://127.0.0.1:1", Duration::from_secs(2)).await;
    assert!(!alive);
    assert!(started.elapsed() < Duration::from_secs(2), "мёртвый порт должен падать быстро");
}

#[tokio::test]
async fn hung_backend_times_out_and_reports_false() {
    let base = spawn_health(true, true).await;
    let started = Instant::now();
    let alive = probe_backend_alive_with(&base, Duration::from_millis(300)).await;
    assert!(!alive, "зависший backend должен считаться мёртвым");
    assert!(started.elapsed() < Duration::from_secs(5), "проб повис — таймаут не сработал");
}
```

- [ ] **Step 2: Запустить — падают**

- [ ] **Step 3: Реализация в `crash.rs`**

```rust
use std::time::Duration;

/// Таймаут проба Python-liveness. **Обязателен:** `proxy::proxy_get_json`
/// использует `Client::new()` БЕЗ таймаута — на зависшем Python (принял TCP,
/// не отвечает) хендлер повис бы, а 5-сек поллинг UI копил бы запросы.
pub const CRASH_PROBE_TIMEOUT: Duration = Duration::from_secs(2);

/// Жив ли Python-backend (адрес берётся у `proxy::python_backend_url()` —
/// env-переопределяемый, без хардкода).
pub async fn probe_backend_alive() -> bool {
    probe_backend_alive_with(&crate::backend::proxy::python_backend_url(), CRASH_PROBE_TIMEOUT)
        .await
}

/// Тестируемое ядро: явные base_url и таймаут.
pub async fn probe_backend_alive_with(base_url: &str, timeout: Duration) -> bool {
    let url = format!("{}/health", base_url.trim_end_matches('/'));
    let client = match reqwest::Client::builder().timeout(timeout).build() {
        Ok(c) => c,
        Err(e) => {
            tracing::debug!("crash probe: не удалось собрать client: {e}");
            return false;
        }
    };
    match client.get(&url).send().await {
        Ok(resp) => resp.status().is_success(),
        Err(e) => {
            tracing::debug!("crash probe: {url} недоступен: {e}");
            false
        }
    }
}

/// Открыть папку с отчётами в проводнике.
///
/// Клиент НЕ передаёт путь (иначе — произвольный reveal + инъекция в
/// командную строку explorer). Открываем папку целиком, не `/select,<file>`.
pub fn reveal_reports_dir(reports_dir: &Path) -> Result<()> {
    std::fs::create_dir_all(reports_dir)
        .with_context(|| format!("создать {}", reports_dir.display()))?;
    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg(reports_dir)
            .spawn()
            .context("не удалось открыть проводник")?;
        Ok(())
    }
    #[cfg(not(windows))]
    {
        anyhow::bail!("reveal поддерживается только на Windows")
    }
}
```

**Замечание реализатору:** happy-path `reveal_reports_dir` (реальный спавн explorer) НЕ юнит-тестируем — это OS-действие, в headless-CI оно бы плодило процессы. Роут-тест (Task 4) покрывает security-критичную ветку 403. Успешный reveal — ручная верификация при живом тесте (в DoD).

- [ ] **Step 4: Прогнать** — `cargo test --test crash_probe` PASS (4).

- [ ] **Step 5: Commit** — `feat(crash): python liveness probe with explicit timeout + reveal`

## Chunk 2: Транспорт + UI

### Task 4: Роуты `/crash/*` + loopback-гейт

**Files:**
- Modify: `src-tauri/src/backend/auth.rs` (`is_loopback` → `pub(crate)`)
- Modify: `src-tauri/src/backend/http.rs` (3 хендлера + 3 роута)
- Test: `src-tauri/tests/crash_routes.rs`

- [ ] **Step 1: Падающие тесты**

`src-tauri/tests/crash_routes.rs`:

```rust
//! Роуты /crash/* через РЕАЛЬНЫЙ auth-обёрнутый роутер.
//! Ключевая проверка безопасности: /crash/reveal — loopback-only (403 с LAN,
//! даже с валидным токеном), клиентский путь не принимается.
use std::net::SocketAddr;
use std::sync::Mutex;

use axum::{body::Body, extract::ConnectInfo, http::Request};
use tower::ServiceExt; // oneshot

use kali_desktop::backend::auth::{self, ControlPlaneToken};
use kali_desktop::backend::http;

const LOOPBACK: &str = "127.0.0.1:54321";
const LAN_PEER: &str = "192.168.1.50:54321";

static TOKEN_ENV_LOCK: Mutex<()> = Mutex::new(());

fn temp_token() -> (ControlPlaneToken, tempfile::TempDir) {
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("control-plane-token");
    let token = {
        let _guard = TOKEN_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("KALI_TOKEN_FILE", &path);
        auth::load_or_create().expect("create token")
    };
    (token, dir)
}

fn req(method: &str, path: &str, peer: &str, token: Option<&str>) -> Request<Body> {
    let peer: SocketAddr = peer.parse().unwrap();
    let mut b = Request::builder().method(method).uri(path);
    if let Some(t) = token {
        b = b.header("X-KALI-Token", t);
    }
    let mut r = b.body(Body::empty()).unwrap();
    // oneshot не заполняет ConnectInfo сам (в проде это делает
    // into_make_service_with_connect_info)
    r.extensions_mut().insert(ConnectInfo(peer));
    r
}

#[tokio::test]
async fn crash_status_answers_with_backend_alive_flag() {
    let (token, _dir) = temp_token();
    let app = auth::with_auth(http::router(), token);
    let res = app
        .oneshot(req("GET", "/crash/status", LOOPBACK, None))
        .await
        .unwrap();
    assert_eq!(res.status(), axum::http::StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 64 * 1024).await.unwrap();
    let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
    // Python в тестах не запущен → false; главное, что поле есть и это bool
    assert!(v["backend_alive"].is_boolean(), "нет backend_alive: {v}");
}

#[tokio::test]
async fn crash_reveal_is_rejected_from_lan_even_with_token() {
    let (token, _dir) = temp_token();
    let token_value = token.value().to_string();
    let app = auth::with_auth(http::router(), token);
    let res = app
        .oneshot(req("POST", "/crash/reveal", LAN_PEER, Some(&token_value)))
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        axum::http::StatusCode::FORBIDDEN,
        "reveal обязан быть loopback-only даже с валидным токеном"
    );
}
```

**Замечание реализатору:** `/crash/report` и happy-path `/crash/reveal` роут-тестами не покрываем: report писал бы в реальный `%APPDATA%`, reveal спавнил бы explorer. Их ядро (`build_report`, `reveal_reports_dir`) покрыто Task 2-3 на temp-dir. Если решишь добавить — понадобится сид `to_bytes(res, CRASH_REPORT_MAX_BYTES * 2)` (не 64 KB) и изоляция APPDATA.

- [ ] **Step 2: Запустить — падают**

- [ ] **Step 3: `is_loopback` → `pub(crate)`**

В `src-tauri/src/backend/auth.rs` (~строка 150) поменять `fn is_loopback(` на `pub(crate) fn is_loopback(`. Больше ничего в auth.rs не трогать.

- [ ] **Step 4: Хендлеры + роуты в `http.rs`**

Добавить рядом с `/updater/*`-блоком (после `updater_install`, перед `router_full`):

```rust
// ── /crash/* (crash opt-in, нативный Rust) ────────────────────────
//
// Stateless: путей/стейта в Extension нет — всё резолвится в crash.rs.
// `/crash/status` = «жив ли Python» (сам факт ответа доказывает, что Rust
// :3006 жив, а значит /crash/report достижим). См. crash.rs + спеку.

async fn crash_status() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "backend_alive": crash::probe_backend_alive().await }))
}

#[derive(serde::Deserialize, Default)]
struct CrashReportReq {
    #[serde(default)]
    reason: Option<String>,
}

async fn crash_report(body: Option<ExtractJson<CrashReportReq>>) -> Response {
    let reason = body.and_then(|ExtractJson(b)| b.reason);
    let build = || -> anyhow::Result<crash::CrashReport> {
        let (logs_dir, reports_dir) = crash::crash_paths()?;
        let meta = crash::CrashMeta {
            version: env!("CARGO_PKG_VERSION"),
            os: std::env::consts::OS,
            arch: std::env::consts::ARCH,
            ts: chrono::Utc::now().to_rfc3339(),
            reason,
        };
        crash::build_report(&logs_dir, &reports_dir, &meta)
    };
    match build() {
        Ok(rep) => (
            StatusCode::OK,
            Json(serde_json::json!({
                "path": rep.path.display().to_string(),
                "text": rep.text,
            })),
        )
            .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}

/// Loopback-only: спаренный LAN-телефон с валидным токеном не должен
/// удалённо открывать проводник на десктопе. Клиентский путь НЕ принимаем.
async fn crash_reveal(connect_info: Option<ConnectInfo<SocketAddr>>) -> Response {
    let is_local = matches!(connect_info, Some(ConnectInfo(peer)) if auth::is_loopback(peer.ip()));
    if !is_local {
        return (
            StatusCode::FORBIDDEN,
            Json(serde_json::json!({ "error": "reveal доступен только локально" })),
        )
            .into_response();
    }
    let done = crash::crash_paths().and_then(|(_, reports_dir)| crash::reveal_reports_dir(&reports_dir));
    match done {
        Ok(()) => (StatusCode::OK, Json(serde_json::json!({ "status": "ok" }))).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}
```

Импорты вверху http.rs (добавить к существующим, не переставляя): `use crate::backend::{auth, crash};`, `use axum::extract::ConnectInfo;`, `use std::net::SocketAddr;` — **проверить, что уже импортировано, и не дублировать**.

В `router_full` добавить 3 роута рядом с `/updater/*` (перед `/ws`):

```rust
        .route("/crash/status", get(crash_status))
        .route("/crash/report", post(crash_report))
        .route("/crash/reveal", post(crash_reveal))
```

- [ ] **Step 5: Прогнать** — `cargo test --test crash_routes --test crash_redact --test crash_report --test crash_probe` PASS + `cargo check --lib` чисто.

- [ ] **Step 6: Commit** — `feat(crash): /crash/* control-plane routes with loopback-only reveal`

### Task 5: `useBackendLiveness` + endpoints

**Files:**
- Modify: `ui/src/api/endpoints.ts`
- Create: `ui/src/hooks/useBackendLiveness.ts`
- Test: `ui/src/hooks/__tests__/useBackendLiveness.test.ts`

- [ ] **Step 1: Падающий тест**

`ui/src/hooks/__tests__/useBackendLiveness.test.ts`:

```ts
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CRASH_POLL_MS, useBackendLiveness } from "../useBackendLiveness";

function reply(alive: boolean) {
  return new Response(JSON.stringify({ backend_alive: alive }));
}

describe("useBackendLiveness", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("не сообщает down, пока стрик не набран", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(false)));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await vi.advanceTimersByTimeAsync(CRASH_POLL_MS + 10); // 2 пробы (mount + 1)
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });

  it("сообщает down после 3 подряд", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(false)));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 3 + 10);
    expect(result.current).toBe(true);
    vi.useRealTimers();
  });

  it("любой alive сбрасывает стрик", async () => {
    let n = 0;
    // Тиков будет 5 (mount + 4 интервала): down, down, UP, down, down
    // → максимум 2 подряд, порог 3 не достигнут.
    // ВНИМАНИЕ: не увеличивать окно — 6-й тик clamp'нется на последний
    // `false` и сфабрикует 3-й подряд down, тест станет ложно-красным.
    const seq = [false, false, true, false, false];
    vi.stubGlobal("fetch", vi.fn(async () => reply(seq[Math.min(n++, seq.length - 1)])));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 4 + 10);
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });

  it("недоступный :3006 (reject) НЕ показывает down — Rust мёртв, вне скоупа", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("refused"); }));
    vi.useFakeTimers();
    const { result } = renderHook(() => useBackendLiveness());
    await vi.advanceTimersByTimeAsync(CRASH_POLL_MS * 4 + 10);
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Запустить** `cd ui; pnpm exec vitest run src/hooks/__tests__/useBackendLiveness.test.ts` → FAIL.

- [ ] **Step 3: Реализация**

`ui/src/api/endpoints.ts` — в конец `RUST_ENDPOINTS`:

```ts
  // Crash opt-in — целиком на Rust control-plane (:3006)
  { method: "GET", path: "/crash/status" },
  { method: "POST", path: "/crash/report" },
  { method: "POST", path: "/crash/reveal" },
```

`ui/src/hooks/useBackendLiveness.ts`:

```ts
import { useEffect, useState } from "react";
import { resolveApiUrl } from "../api/endpoints";

/** Интервал проба Python-liveness. */
export const CRASH_POLL_MS = 5000;
/** Сколько «down» подряд до показа промпта (~15с — переживает медленный старт
 *  Python, где wait_for_backend_ready даёт 5с, и отсекает транзиентные блипы). */
export const CRASH_DOWN_STREAK = 3;

/**
 * true — Python-backend уверенно мёртв (а Rust :3006 жив, раз ответил).
 * Если сам :3006 недоступен (reject) — false: Rust мёртв, промпт бессмысленен
 * (его транспорт на том же сервере), это вне скоупа фичи.
 */
export function useBackendLiveness(): boolean {
  const [down, setDown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let streak = 0;

    const tick = async () => {
      try {
        const res = await fetch(resolveApiUrl("/crash/status", "GET"), { method: "GET" });
        if (!res.ok) throw new Error(String(res.status));
        const { backend_alive: alive } = (await res.json()) as { backend_alive: boolean };
        if (cancelled) return;
        if (alive) {
          streak = 0;
          setDown(false);
        } else {
          streak += 1;
          if (streak >= CRASH_DOWN_STREAK) setDown(true);
        }
      } catch {
        // :3006 не ответил — Rust мёртв; промпт не показываем
        if (!cancelled) {
          streak = 0;
          setDown(false);
        }
      }
    };

    void tick();
    const id = setInterval(tick, CRASH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return down;
}
```

- [ ] **Step 4: Прогнать** — тест PASS; `pnpm exec vitest run` целиком не сломан.

- [ ] **Step 5: Commit** — `feat(ui): backend liveness hook + crash endpoints`

### Task 6: `CrashReportPrompt` + монтаж в App

**Files:**
- Create: `ui/src/components/CrashReportPrompt.tsx`
- Modify: `ui/src/App.tsx`
- Test: `ui/src/__tests__/CrashReportPrompt.test.tsx`

- [ ] **Step 1: Падающий тест**

`ui/src/__tests__/CrashReportPrompt.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CrashReportPrompt } from "../components/CrashReportPrompt";

function statusReply(alive: boolean) {
  return new Response(JSON.stringify({ backend_alive: alive }));
}
function reportReply() {
  return new Response(
    JSON.stringify({ path: "C:\\KALI\\crash-reports\\crash-1.txt", text: "KALI crash report\nline" }),
  );
}

/** fetch-роутер: /crash/status → alive-флаг, /crash/report → отчёт. */
function stubFetch(alive: boolean, onReport?: () => void) {
  return vi.fn(async (url: string) => {
    if (String(url).includes("/crash/status")) return statusReply(alive);
    if (String(url).includes("/crash/report")) {
      onReport?.();
      return reportReply();
    }
    return new Response("{}");
  });
}

describe("CrashReportPrompt", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("не рендерится, пока backend жив", async () => {
    vi.stubGlobal("fetch", stubFetch(true));
    const { container } = render(<CrashReportPrompt />);
    await waitFor(() => expect(container.firstChild).toBeNull());
  });

  it("opt-in: /crash/report НЕ зовётся до клика", async () => {
    const onReport = vi.fn();
    vi.stubGlobal("fetch", stubFetch(false, onReport));
    render(<CrashReportPrompt />);
    await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    expect(onReport).not.toHaveBeenCalled();
  }, 25000);

  it("клик собирает отчёт и показывает путь + кнопки", async () => {
    vi.stubGlobal("fetch", stubFetch(false));
    const user = userEvent.setup();
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    expect(await screen.findByText(/crash-1\.txt/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /открыть папку/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /копировать/i })).toBeInTheDocument();
  }, 25000);

  it("«Открыть папку» шлёт POST /crash/reveal БЕЗ пути в теле", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
        calls.push(u);
        if (u.includes("/crash/status")) return statusReply(false);
        if (u.includes("/crash/report")) return reportReply();
        if (u.includes("/crash/reveal")) {
          // клиентский путь не передаём — сервер сам знает reports_dir
          expect(init?.body ?? null).toBeNull();
          return new Response(JSON.stringify({ status: "ok" }));
        }
        return new Response("{}");
      }),
    );
    const user = userEvent.setup();
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    await user.click(await screen.findByRole("button", { name: /открыть папку/i }));
    await waitFor(() => expect(calls.some((u) => u.includes("/crash/reveal"))).toBe(true));
  }, 25000);

  it("«Копировать» кладёт полный текст отчёта в буфер", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("fetch", stubFetch(false));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const user = userEvent.setup();
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    await user.click(await screen.findByRole("button", { name: /копировать/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("KALI crash report\nline"));
  }, 25000);

  it("ошибка сборки показывается честно", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/crash/status")) return statusReply(false);
        return new Response(JSON.stringify({ error: "disk full" }), { status: 500 });
      }),
    );
    const user = userEvent.setup();
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    expect(await screen.findByText(/не удалось собрать отчёт/i)).toBeInTheDocument();
  }, 25000);
});
```

**Замечание реализатору:** тесты ждут реального 15-секундного стрика (3 × 5с) — поэтому `timeout: 20000` у `findByRole` и 25с у теста. Если это окажется медленно, оберни ожидание в фейк-таймеры (`vi.useFakeTimers()` + `advanceTimersByTimeAsync`) — но userEvent требует `advanceTimers` в setup; проще оставить реальные, тестов всего 4.

- [ ] **Step 2: Запустить — FAIL**

- [ ] **Step 3: Реализация**

`ui/src/components/CrashReportPrompt.tsx` (стиль — как соседние баннеры в App.tsx: css-переменные `--j-*`, fixed-оверлей, без новых зависимостей):

```tsx
import { useState } from "react";
import { resolveApiUrl } from "../api/endpoints";
import { useBackendLiveness } from "../hooks/useBackendLiveness";

type Phase = "idle" | "building" | "ready" | "error";
interface Report {
  path: string;
  text: string;
}
/** Сколько строк отчёта показываем в превью (юзер видит, что отправляет). */
const PREVIEW_LINES = 30;

/**
 * Opt-in промпт отчёта о сбое. Появляется, только когда Python-backend
 * уверенно мёртв; НИЧЕГО не собирает и не отправляет до клика. Сток локальный —
 * пользователь сам передаёт .txt. Спека: 2026-07-14-crash-optin-design.md
 */
export function CrashReportPrompt() {
  const backendDown = useBackendLiveness();
  const [phase, setPhase] = useState<Phase>("idle");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!backendDown) return null;

  const build = async () => {
    setPhase("building");
    setError(null);
    try {
      const res = await fetch(resolveApiUrl("/crash/report", "POST"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(String(res.status));
      setReport((await res.json()) as Report);
      setPhase("ready");
    } catch {
      setError("Не удалось собрать отчёт — открой папку данных KALI и передай логи вручную.");
      setPhase("error");
    }
  };

  const reveal = async () => {
    try {
      await fetch(resolveApiUrl("/crash/reveal", "POST"), { method: "POST" });
    } catch {
      /* путь показан текстом — юзер откроет вручную */
    }
  };

  const copy = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.text);
    } catch {
      // буфер недоступен (нет прав/окружения) — путь к файлу показан выше,
      // юзер откроет его сам; молча деградируем, не роняем промпт
    }
  };

  return (
    <div
      className="fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border p-4 shadow-lg text-sm"
      style={{
        background: "var(--j-surface, #111)",
        borderColor: "var(--j-border, #333)",
        color: "var(--j-text, #eee)",
      }}
      role="status"
    >
      {phase === "ready" && report ? (
        <>
          <div className="font-semibold">Отчёт готов</div>
          <div className="mt-1 break-all" style={{ color: "var(--j-text-dim, #aaa)" }}>
            {report.path}
          </div>
          <details className="mt-2">
            <summary className="cursor-pointer" style={{ color: "var(--j-text-dim, #aaa)" }}>
              Что внутри
            </summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs">
              {report.text.split("\n").slice(0, PREVIEW_LINES).join("\n")}
            </pre>
          </details>
          <div className="mt-2 flex items-center gap-2">
            <button
              className="rounded-lg px-3 py-1 font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void reveal()}
            >
              Открыть папку
            </button>
            <button
              className="px-2 py-1"
              style={{ color: "var(--j-text-dim, #aaa)" }}
              onClick={() => void copy()}
            >
              Копировать
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="font-semibold">Похоже, ядро аварийно остановилось</div>
          <div className="mt-1" style={{ color: "var(--j-text-dim, #aaa)" }}>
            {phase === "error"
              ? error
              : "Подготовить отчёт для разработчика, чтобы это починить? Отчёт сохранится файлом — отправишь его сам."}
          </div>
          <div className="mt-2">
            <button
              className="rounded-lg px-3 py-1 font-medium disabled:opacity-50"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              disabled={phase === "building"}
              onClick={() => void build()}
            >
              {phase === "building" ? "Собираю…" : "Подготовить отчёт"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
```

`ui/src/App.tsx`: импорт + монтаж **рядом** с существующим `kernelStage`-блоком (после его тернарника, на том же уровне) — существующую логику баннера НЕ трогать:

```tsx
import { CrashReportPrompt } from "./components/CrashReportPrompt";
// ...
      <CrashReportPrompt />
```

- [ ] **Step 4: Прогнать** — `pnpm exec vitest run` целиком PASS (без регрессий).

- [ ] **Step 5: Commit** — `feat(ui): opt-in crash report prompt`

## Chunk 3: CI и финал

### Task 7: CI-шаг + полный прогон + push

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: CI — гонять crash-тесты**

В `.github/workflows/ci.yml`, rust-джоб, **добавить crash-сюиты в существующий шаг** «Updater tests» (переименовав его) — не плодить шаг:

```yaml
      - name: Rust native suites (loopback-only, no audio deps)
        run: cargo test --test updater_core --test updater_download --test updater_flow --test updater_install --test updater_routes --test crash_redact --test crash_report --test crash_probe --test crash_routes
        working-directory: src-tauri
        env:
          CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER: link.exe
          # updater_* бинарники триггерят Windows Installer Detection (error 740);
          # RunAsInvoker shim обходит авто-elevation (защитно — на случай не-админ раннера).
          __COMPAT_LAYER: RunAsInvoker
```

- [ ] **Step 2: Полный прогон гейтов**

```
cd src-tauri; cargo test --test crash_redact --test crash_report --test crash_probe --test crash_routes; cargo check --lib
cd src-tauri; $env:__COMPAT_LAYER='RunAsInvoker'; cargo test --test updater_core --test updater_download --test updater_flow --test updater_install --test updater_routes
cd ui; pnpm exec vitest run
.venv\Scripts\python.exe -m pytest -m core_loop -q
.venv\Scripts\python.exe -m pytest tests/scripts -q
```

Ожидаемо: **crash 21** (redact 10 · report 5 · probe 4 · routes 2) · updater 21 · ui 162+6 · core_loop 13 · scripts 12. Всё зелёное (kernel/updater/scripts этим планом не трогались).

- [ ] **Step 3: Commit + push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run crash suites alongside updater in the rust job"
git push origin main
```

- [ ] **Step 4: Проверить CI зелёный**

`gh run watch $(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status`

**Definition of Done:**
1. Промпт появляется, когда Python мёртв (стрик 3) И :3006 жив; до клика ничего не собирается.
2. Клик → отредактированный `crash-<ts>.txt` в `crash-reports/`; «Открыть папку» и «Копировать» работают.
3. `redact()` маскирует классы 1-6; анти-FP негативы зелёные; over-mask задокументирован.
4. `/crash/reveal` — loopback-only (403 с LAN проверено тестом), клиентский путь не принимается.
5. Все существующие гейты зелёные; CI зелёный.
6. **Ручная верификация (не код-гейт, в релизный чеклист):** убить `kali-backend.exe` в диспетчере при живом UI → через ~15с появляется промпт → «Подготовить отчёт» → «Открыть папку» реально открывает проводник с файлом → глазами проверить, что в .txt нет секретов/имени пользователя.
