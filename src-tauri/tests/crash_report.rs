//! Сборка отчёта: хвост логов, фолбэк без логов, бюджет байтов, редакция.
use kali_desktop::backend::crash::{
    build_report, CrashMeta, CRASH_LOG_FILES, CRASH_REASON_MAX_CHARS, CRASH_REPORT_MAX_BYTES,
};

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
    // Пер-файловая пометка ДЛЯ КАЖДОГО лога...
    for name in CRASH_LOG_FILES {
        assert!(
            rep.text.contains(&format!("--- {name}: логи не найдены ---")),
            "нет пер-файловой пометки для {name}: {}",
            rep.text
        );
    }
    // ...И отдельная сводка «вообще ничего не нашли». Раньше тест проходил на
    // одной лишь пер-файловой строке, поэтому ветка `if !any_log` была
    // неотличима от своего отсутствия.
    assert!(
        rep.text.contains("(логи не найдены — отчёт содержит только мету)"),
        "нет сводки meta-only: {}",
        rep.text
    );
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

    // Пустой ≠ отсутствующий: пустой err РЕНДЕРИТСЯ секцией (пустое тело), а не
    // пометкой «не найдены»; отсутствующий out — наоборот. И раз хоть один лог
    // прочитан, сводки meta-only быть НЕ должно. Раньше не проверялось ничего.
    assert!(
        rep.text.contains(&format!(
            "--- {} (последние 400 строк, отредактировано) ---",
            CRASH_LOG_FILES[0]
        )),
        "пустой лог должен рендериться секцией: {}",
        rep.text
    );
    assert!(
        !rep.text.contains(&format!("--- {}: логи не найдены ---", CRASH_LOG_FILES[0])),
        "пустой лог помечен как отсутствующий: {}",
        rep.text
    );
    assert!(
        rep.text.contains(&format!("--- {}: логи не найдены ---", CRASH_LOG_FILES[1])),
        "отсутствующий out должен быть помечен: {}",
        rep.text
    );
    assert!(
        !rep.text.contains("отчёт содержит только мету"),
        "сводки meta-only быть не должно — err прочитан: {}",
        rep.text
    );
}

/// Minor-3 (ревью): в Chunk 2 `reason` приходит ИЗ ТЕЛА ЗАПРОСА =
/// клиент-контролируем. Бюджет логов считается ПОСЛЕ шапки и её саму не
/// ограничивает, поэтому без клампа большой `reason` уносил отчёт за
/// `CRASH_REPORT_MAX_BYTES` (замерено ревьюером: 524563 > 262144) — и
/// «жёсткий предел» переставал быть жёстким.
#[test]
fn oversized_client_supplied_reason_is_clamped() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("logs");
    let reports = tmp.path().join("crash-reports");
    std::fs::create_dir_all(&logs).unwrap();

    let mut m = meta();
    m.reason = Some("R".repeat(600_000));
    let rep = build_report(&logs, &reports, &m).unwrap();

    assert!(
        rep.text.len() <= CRASH_REPORT_MAX_BYTES,
        "отчёт {} > предела — reason не заклампан",
        rep.text.len()
    );
    assert!(rep.text.contains("обрезано"), "нет маркера обрезки reason");
    assert!(
        !rep.text.contains(&"R".repeat(CRASH_REASON_MAX_CHARS + 1)),
        "reason длиннее предела попал в отчёт"
    );
}

/// Многобайтный `reason` не должен рваться посередине символа (кламп по
/// СИМВОЛАМ, не байтам) — иначе отчёт был бы невалидным UTF-8/с U+FFFD.
#[test]
fn multibyte_reason_clamp_does_not_split_chars() {
    let tmp = tempfile::tempdir().unwrap();
    let logs = tmp.path().join("logs");
    let reports = tmp.path().join("crash-reports");
    std::fs::create_dir_all(&logs).unwrap();

    let mut m = meta();
    m.reason = Some("я".repeat(CRASH_REASON_MAX_CHARS * 3));
    let rep = build_report(&logs, &reports, &m).unwrap();

    assert!(!rep.text.contains('\u{FFFD}'), "reason разрублен посередине символа");
    assert_eq!(
        rep.text.matches('я').count(),
        CRASH_REASON_MAX_CHARS,
        "должно остаться ровно CRASH_REASON_MAX_CHARS символов"
    );
}
