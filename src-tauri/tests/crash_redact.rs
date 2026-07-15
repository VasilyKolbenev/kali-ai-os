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

/// Регрессия (ревью): прежний `\bauthorization:\s*.+` требовал `:` СРАЗУ после
/// слова → все кавычечные/dict-формы утекали. Это ровно то, что печатают
/// httpx/requests/uvicorn на debug-уровне; credential (12 символов) короче
/// порога любой руны, так что ниже его не ловил никто.
#[test]
fn masks_authorization_in_quoted_and_dict_forms() {
    for input in [
        r#"{"authorization": "Basic dXNlcjpwYXNz"}"#,
        r#"headers={'Authorization': 'Basic dXNlcjpwYXNz'}"#,
        r#"authorization="Basic dXNlcjpwYXNz""#,
        r#"AUTHORIZATION = "Bearer dXNlcjpwYXNz""#,
    ] {
        let out = redact(input);
        assert!(!out.contains("dXNlcjpwYXNz"), "credential утёк из {input:?}: {out}");
        assert!(out.contains("***REDACTED***"), "не замаскировано {input:?}: {out}");
    }
}

/// Анти-FP той же правки: без `:`/`=` после слова — обычная проза, не трогаем.
#[test]
fn does_not_mask_authorization_prose() {
    let input = "authorization failed for user bob";
    assert_eq!(redact(input), input, "ложное срабатывание на прозе");
}

/// Секрет-заголовки: RE_ASSIGN ловит только `=`, поэтому header-форма с `:`
/// (`xi-api-key:` у ElevenLabs) раньше утекала целиком.
#[test]
fn masks_secret_headers_in_colon_form() {
    for (input, secret) in [
        ("xi-api-key: abc123def456", "abc123def456"),
        (r#"{"x-api-key": "sk_live_short"}"#, "sk_live_short"),
        ("api-key: mysecretvalue", "mysecretvalue"),
    ] {
        let out = redact(input);
        assert!(!out.contains(secret), "секрет-заголовок утёк из {input:?}: {out}");
    }
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

/// Регрессия (ревью): руна с `/` в наборе матчилась ЧЕРЕЗ разделители и
/// уничтожала диагностику. Обе фикстуры ЭМПИРИЧЕСКИ ловили старый паттерн:
/// путь схлопывался в `path C:/***REDACTED***`, URL — в
/// `GET https://huggingface.***REDACTED***`. Последняя — РУТИННАЯ строка KALI
/// (F5-TTS тянет модели с HF), то есть отчёт удалял ровно то, ради чего он есть.
#[test]
fn does_not_eat_urls_and_forward_slash_paths() {
    // ≥40 символов подряд без `-`/`.` — старый паттерн это съедал целиком
    let hf = "GET https://huggingface.co/SWivid/F5TTS/resolve/main/model/weights";
    assert_eq!(redact(hf), hf, "HF-URL съеден руной — диагностика уничтожена");

    // forward-slash путь: диагностика выживает, а имя пользователя ОБЯЗАНО
    // быть замаскировано (без `/` в руне до пути наконец доходит RE_WIN_USER_PATH)
    let out = redact("path C:/Users/Vasily/AppData/Roaming/KALI/models");
    assert!(!out.contains("Vasily"), "username утёк: {out}");
    assert!(out.contains("<user>"), "нет плейсхолдера: {out}");
    assert!(
        out.contains("AppData/Roaming/KALI/models"),
        "остаток пути съеден — диагностика потеряна: {out}"
    );
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

/// Идемпотентность НОВЫХ паттернов (их замены сами содержат `:` и потому
/// потенциально самоматчатся — проверяем, что второй проход ничего не меняет).
#[test]
fn new_patterns_are_idempotent() {
    for input in [
        r#"{"authorization": "Basic dXNlcjpwYXNz"}"#,
        "Authorization: Basic dXNlcjpwYXNz",
        "xi-api-key: abc123def456",
        r#"{"x-api-key": "sk_live_short"}"#,
    ] {
        let once = redact(input);
        assert_eq!(redact(&once), once, "не идемпотентно для {input:?}: {once}");
    }
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
