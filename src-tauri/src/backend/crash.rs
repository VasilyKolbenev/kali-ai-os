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
