//! Crash opt-in: редакция логов, сборка отчёта, проб liveness, reveal.
//!
//! Спека: docs/superpowers/specs/2026-07-14-crash-optin-design.md
//! Сток ЛОКАЛЬНЫЙ — отчёт пишется в файл, пользователь передаёт его сам.
//! Ничего не собирается и не отправляется без явного клика.

use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::Duration;

use anyhow::{Context, Result};
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
/// есть дальше его никто не поймает = утечка).
///
/// **Кавычки и `=` (правка ревью):** прежний `\bauthorization:\s*.+` требовал
/// `:` СРАЗУ после слова и потому пропускал ровно те формы, которые печатают
/// httpx/requests/uvicorn на debug-уровне:
/// `{"authorization": "Basic …"}`, `headers={'Authorization': 'Basic …'}`,
/// `authorization="Basic …"` — всё это утекало нетронутым (credential короче
/// 40 символов → ни одна руна ниже его не ловит).
/// Теперь: опц. кавычка после слова, `:` ИЛИ `=`, опц. открывающая кавычка,
/// значение до закрывающей кавычки/конца строки. `[^"'\r\n]+` держит матч
/// однострочным — следующие строки лога целы. Анти-FP жив: в
/// `authorization failed for user bob` нет `:`/`=` → не матчится.
static RE_AUTHORIZATION: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"(?i)\bauthorization["']?\s*[:=]\s*["']?[^"'\r\n]+"#).unwrap());
/// Секрет-заголовки: `x-api-key:` / `xi-api-key:` (ElevenLabs) / `api-key:`.
/// RE_ASSIGN ниже ловит только `=`, поэтому header-форма с `:` утекала.
static RE_SECRET_HEADER: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?i)\b(x-api-key|xi-api-key|api-key)["']?\s*[:=]\s*["']?[^\s"',}]+"#).unwrap()
});
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
/// base64-руна **БЕЗ `/` в наборе (правка ревью)**.
///
/// С `/` руна матчилась ЧЕРЕЗ разделители путей и URL и уничтожала ровно ту
/// диагностику, ради которой отчёт и существует:
/// - `path C:/Users/Vasily/AppData/Roaming/KALI/models` → `path C:/***REDACTED***`
///   (и RE_WIN_USER_PATH до пути уже не доходил — руна съедала его первой);
/// - `GET https://huggingface.co/SWivid/F5TTS/resolve/main/model/weights`
///   → `GET https://huggingface.***REDACTED***` — а это РУТИННАЯ строка для
///   KALI (F5-TTS тянет модели с HF).
///
/// Почему убрать `/` безопасно: ни один секрет в стеке KALI не является голой
/// standard-alphabet base64-руной, которой нужен `/` — control-plane токен это
/// 64 hex (RE_HEX_RUN), JWT это base64url с `-`/`_` (RE_JWT), ключи
/// OpenAI/Anthropic/Google префиксованы (RE_KEY_SK/RE_KEY_GOOGLE), Basic-креды
/// короче 40 (их берёт RE_AUTHORIZATION). Остаточный зазор — голый,
/// бесконтекстный, содержащий `/`, ≥40-символьный base64-секрет: в стеке такого
/// нет, а бесконтекстными секреты в логах почти не бывают (их ловят
/// assignment/Bearer/Authorization). Это гипотетика против ГАРАНТИРОВАННОГО,
/// рутинного, убивающего диагностику over-mask.
///
/// Побочный плюс: без `/` до forward-slash путей теперь доходит
/// RE_WIN_USER_PATH и реально маскирует имя пользователя.
static RE_B64_RUN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[A-Za-z0-9+]{40,}={0,2}\b").unwrap());
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
    let s = RE_SECRET_HEADER.replace_all(&s, format!("${{1}}: {MASK}").as_str());
    let s = RE_ASSIGN.replace_all(&s, format!("${{1}}={MASK}").as_str());
    let s = RE_CONN.replace_all(&s, "${1}://${2}:***@");
    let s = RE_HEX_RUN.replace_all(&s, MASK);
    let s = RE_B64_RUN.replace_all(&s, MASK);
    let s = RE_EMAIL.replace_all(&s, "***@***");
    let s = RE_WIN_USER_PATH.replace_all(&s, "${1}<user>");
    s.into_owned()
}

/// Сколько последних строк каждого лога берём.
pub const CRASH_LOG_TAIL_LINES: usize = 400;
/// Жёсткий предел итогового отчёта.
pub const CRASH_REPORT_MAX_BYTES: usize = 256 * 1024;
/// Сколько байт с конца файла сканируем ради хвоста (лог может быть огромным —
/// целиком в память не читаем).
const CRASH_TAIL_SCAN_BYTES: u64 = 1024 * 1024;
/// Предел длины `reason`. В Chunk 2 `reason` приходит ИЗ ТЕЛА ЗАПРОСА, то есть
/// клиент-контролируем: без клампа мегабайтный `reason` унёс бы отчёт далеко за
/// `CRASH_REPORT_MAX_BYTES` (бюджет логов считается ПОСЛЕ шапки и саму шапку не
/// ограничивает) — тогда «жёсткий предел» перестал бы быть жёстким.
pub const CRASH_REASON_MAX_CHARS: usize = 500;
const CRASH_TRUNCATED_MARKER: &str = "…(обрезано)";
/// Источники в порядке убывания диагностической ценности. Порядок = порядок
/// секций в отчёте (что важнее — то выше и переживает беглый взгляд).
pub const CRASH_LOG_FILES: [&str; 3] = [
    "kali-backend.err.log",  // сырой stderr шелл-спавна: ловит то, что ПРОХОДИТ МИМО
                             // логгера (паники, C-уровень, падение до init логирования)
    "kali-backend.log",      // собственный файловый лог Python — самая богатая
                             // диагностика; единственный источник при frozen/прямом
                             // запуске (шелл тогда stdout/stderr не перенаправляет)
    "kali-backend.out.log",  // обычно ПУСТ (Python пишет в stderr) — держим на случай
                             // print()/сторонних либ; пустая секция стоит ~0 байт
];

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
///
/// Причина `None` логируется с контекстом (домашнее правило): «нет файла» и
/// «файл есть, но не читается» (залочен, нет прав) — разные истории, а в отчёт
/// обе попадают одной строкой «логи не найдены», что для второй нечестно.
fn tail_lines(path: &Path, n: usize) -> Option<String> {
    macro_rules! bail_io {
        ($e:expr, $what:literal) => {
            match $e {
                Ok(v) => v,
                Err(e) => {
                    tracing::debug!("crash: {} {}: {e}", $what, path.display());
                    return None;
                }
            }
        };
    }

    let mut file = match std::fs::File::open(path) {
        Ok(f) => f,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            tracing::debug!("crash: лога нет: {}", path.display());
            return None;
        }
        Err(e) => {
            tracing::debug!("crash: лог не открывается (залочен/нет прав) {}: {e}", path.display());
            return None;
        }
    };
    let len = bail_io!(file.metadata(), "метаданные лога недоступны").len();
    let start = len.saturating_sub(CRASH_TAIL_SCAN_BYTES);
    bail_io!(file.seek(SeekFrom::Start(start)), "seek по логу не удался");
    let mut buf = Vec::new();
    bail_io!(file.read_to_end(&mut buf), "чтение лога не удалось");

    let text = String::from_utf8_lossy(&buf);
    let mut lines: Vec<&str> = text.lines().collect();
    // Сканировали с середины файла → первая строка почти наверняка обрезана
    // посередине. Выкидываем её: (1) срез мог разрубить UTF-8 символ, и
    // from_utf8_lossy оставил бы U+FFFD; (2) разрубленный секрет теряет
    // `\b`-якорь и мог бы не совпасть с паттернами редакции.
    if start > 0 && !lines.is_empty() {
        lines.remove(0);
    }
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
/// Секции идут в порядке `CRASH_LOG_FILES` (err → app-log → out). Бюджет байт
/// делится ПОРОВНУ между источниками, а не режется общим краем: иначе самый
/// объёмный лог (на практике — `kali-backend.log`, у Vasily 967 KB против 7 KB
/// у `err`) вытеснил бы остальные секции целиком.
pub fn build_report(logs_dir: &Path, reports_dir: &Path, meta: &CrashMeta) -> Result<CrashReport> {
    // Кламп по СИМВОЛАМ (не байтам) — не рвём UTF-8. `reason` клиент-контролируем
    // (см. CRASH_REASON_MAX_CHARS), поэтому ограничиваем до сборки шапки.
    let reason: String = match meta.reason.as_deref() {
        None => "-".to_string(),
        Some(r) if r.chars().count() > CRASH_REASON_MAX_CHARS => {
            r.chars().take(CRASH_REASON_MAX_CHARS).collect::<String>() + CRASH_TRUNCATED_MARKER
        }
        Some(r) => r.to_string(),
    };
    let mut report = format!(
        "KALI crash report\nversion: {}\nos: {} / {}\ntime: {}\nreason: {}\n",
        meta.version, meta.os, meta.arch, meta.ts, reason,
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

/// Переиспользуемый клиент проба. UI поллит `/crash/status` каждые 5с
/// бессрочно — сборка нового `Client` на каждый проб жгла бы connection-pool и
/// TLS-конфиг вхолостую. Таймаут ставится ПО-ЗАПРОСНО (`.timeout()` на
/// RequestBuilder, прецедент — `updater.rs`), поэтому клиент общий, а
/// `probe_backend_alive_with` остаётся тестируемым с инжектируемым таймаутом.
static PROBE_CLIENT: LazyLock<reqwest::Client> = LazyLock::new(reqwest::Client::new);

/// Тестируемое ядро: явные base_url и таймаут.
pub async fn probe_backend_alive_with(base_url: &str, timeout: Duration) -> bool {
    let url = format!("{}/health", base_url.trim_end_matches('/'));
    match PROBE_CLIENT.get(&url).timeout(timeout).send().await {
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
