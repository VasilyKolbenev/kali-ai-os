# Crash opt-in (Track4 #2) — Design

> **Дата:** 2026-07-14 · **Статус:** утверждён Vasily (подход A: HTTP-роуты `/crash/*` на :3006 + opt-in секция в баннере). Спека → план (writing-plans) → TDD.
> **Binding-ограничения Vasily:** (1) **без хардкода** — пути через существующий `runtime_data_dir()`, паттерны редакции/размеры хвоста = именованные константы; (2) **ничего не ломать** — только аддитивно, все существующие тесты остаются зелёными.

## Контекст (как краши всплывают сегодня)

- Десктоп-шелл (Tauri, `kali-desktop.exe`) спавнит `kali-backend.exe` дочерним процессом; stdout/stderr → `%APPDATA%/KALI/logs/kali-backend.out.log` и `.err.log` (через `runtime_data_dir()` — `src-tauri/src/lib.rs:51,62-67`).
- При старт-фейле (exe не найден / не healthy за 5с / spawn упал) Rust эмитит `backend://failed` (`lib.rs:145,197,208`).
- UI: `useKernelStage()` (`App.tsx:24`) по обрыву WebSocket доходит до stage 2 (>12с недоступности) → красный баннер «Ядро не запустилось» (`App.tsx:99-111`). Этот баннер появляется на ОБА выбранных триггера (старт-фейл И смерть посреди сессии), т.к. в обоих случаях WS не отвечает.
- Логи лежат локально; Vasily собирает их с друзей вручную.

**Ключевая посылка (verify при имплементации):** упал именно **Python-backend**; **Rust-контрол-плейн на :3006 — отдельный поток десктоп-шелла** (`lib.rs` setup спавнит axum в `std::thread`), живёт независимо от дочернего процесса. Значит UI может достучаться до Rust по HTTP :3006 даже когда backend мёртв. Rust-паники самого шелла — вне скоупа v1 (тогда webview тоже мёртв).

## Что строим (подход A)

Opt-in: **на краше ничего не собирается и не отправляется, пока пользователь не нажал кнопку.** Сток локальный — юзер сам передаёт файл (Telegram/почта). Это делает фичу совместимой с [[feedback-app-minimalism]] (не постоянная инструментация, а разовое согласие при аварии) и снимает юр-риск отправки данных без юрлица.

## Компоненты и файлы

| Компонент | Файл | Ответственность |
|---|---|---|
| Редактор + сборщик (Rust) | `src-tauri/src/backend/crash.rs` (NEW) | `redact(&str)->String`, `build_report(logs_dir, reports_dir, meta)->Result<CrashReport>`, `reveal(&Path)->Result<()>`; всё чисто/тестируемо |
| Роуты | `src-tauri/src/backend/http.rs` (modify) | `POST /crash/report`, `POST /crash/reveal` — аппенд к существующим роутам, как `/updater/*` (без смены сигнатуры `router_full`) |
| Модуль | `src-tauri/src/backend/mod.rs` (modify) | `pub mod crash;` (алфавитно) |
| UI-промпт | `ui/src/components/CrashReportPrompt.tsx` (NEW) | локальный state `idle→building→ready→error`; кнопки Подготовить / Открыть папку / Копировать |
| Монтаж | `ui/src/App.tsx` (modify) | вставить `<CrashReportPrompt/>` ВНУТРЬ существующего `kernelStage === 2` баннера (не переструктурировать баннер) |
| Endpoints | `ui/src/api/endpoints.ts` (modify) | +2 записи `RUST_ENDPOINTS` (POST /crash/report, POST /crash/reveal) |

## Данные / поток

1. `kernelStage === 2` → баннер рендерит `<CrashReportPrompt/>` с текстом «Похоже, ядро аварийно остановилось. Подготовить отчёт для разработчика, чтобы починить?» + `[Подготовить отчёт]`.
2. Клик → `POST /crash/report` (тело пустое или `{reason?}` — reason опционален). Rust:
   - читает **последние `CRASH_LOG_TAIL_LINES` (=400)** строк из `kali-backend.out.log` и `.err.log` (каждый файл — свой хвост), общий предел `CRASH_REPORT_MAX_BYTES` (=256 KB) на итог;
   - собирает мету: `version` (`env!("CARGO_PKG_VERSION")`), `os`/`arch` (`std::env::consts::OS/ARCH`), `ts` (`chrono::Utc::now()` — chrono уже dep), `reason` (если передан);
   - прогоняет всё через `redact()`;
   - пишет `reports_dir/crash-<ISO8601-safe>.txt` (reports_dir = `runtime_data_dir().join("crash-reports")`, `create_dir_all`);
   - возвращает `{ path: String, text: String }` (весь редактированный отчёт — он капнут, вернуть безопасно).
3. UI: показывает путь + свёрнутое превью (первые ~30 строк `text`) + `[Открыть папку]` (→ `POST /crash/reveal` с `{path}`) + `[Копировать текст]` (webview `navigator.clipboard.writeText(text)` — без tauri).
4. Юзер тащит .txt в чат Васе или вставляет скопированный текст.

**Формат отчёта** — читаемый .txt (юзер может открыть глазами = прозрачность):
```
KALI crash report
version: 1.0.0-rc1
os: windows / x86_64
time: 2026-07-14T16:40:00Z
reason: backend did not become healthy within 5s

--- kali-backend.err.log (last 400 lines, redacted) ---
<redacted tail>

--- kali-backend.out.log (last 400 lines, redacted) ---
<redacted tail>
```

## Редакция (safety-critical — сердце фичи)

`redact()` — последовательность regex-проходов, **консервативно (лучше пере-замаскировать)**. Все паттерны — именованные константы в `crash.rs` (без хардкода в теле). Классы:

| Класс | Паттерн (ориентир) | Замена |
|---|---|---|
| Ключи с префиксом | `sk-ant-…`, `sk-…`, Google `AIza[0-9A-Za-z_-]{35}` | `***REDACTED***` |
| Bearer / assignment | `(?i)bearer\s+\S+`, `(?i)(api[_-]?key\|token\|secret)\s*[=:]\s*\S+` | `<ключ>=***REDACTED***` |
| Длинные секрет-руны | hex `\b[0-9a-fA-F]{32,}\b`, base64-подобные `\b[A-Za-z0-9+/]{40,}={0,2}\b` | `***REDACTED***` |
| Windows-путь | `(?i)([a-z]:\\users\\)[^\\/]+`, forward-slash форма, `%USERPROFILE%` | `$1<user>` |
| Email | `\b[\w.+-]+@[\w-]+\.[\w.-]+\b` | `***@***` |

**Порядок важен:** сначала ключи/руны (специфичные), потом пути, потом email — чтобы маскировка путей не съела токен раньше времени. IP НЕ маскируем (диагностично, низкая чувствительность).

**Честная граница:** редакция — defense-in-depth, НЕ гарантия. Два предохранителя: (1) .txt читаемый, юзер видит что отправляет (финальный человеческий гейт согласия); (2) сток локальный — отправка только по решению юзера. Анти-false-positive: обычные слова/пути без секрет-формы НЕ маскируются (тестируется явно).

## Ошибки

| Сценарий | Поведение |
|---|---|
| Логи-папка/файлы отсутствуют или пусты | Отчёт только с метой (version/os/reason) + строка «логи не найдены»; НЕ падаем, `/crash/report` = 200 |
| Запись отчёта не удалась (диск/права) | `/crash/report` = 500 `{error}`; UI: «Не удалось собрать отчёт» + подсказка открыть папку логов вручную |
| `reveal` упал (нет explorer и т.п.) | `/crash/reveal` = 500; UI показывает путь текстом для ручного открытия |
| Всегда | Никакого авто-сбора и авто-отправки; сбор только по клику |

## Тесты (TDD)

- **Rust** (`src-tauri/tests/crash_*.rs`): `redact()` по каждому классу отдельно + комбо + **анти-false-positive** (обычный текст/путь без секрета не меняется); `build_report` (хвост N строк, пустые/отсутствующие логи → мета-only fallback, cap по байтам, порядок секций); smoke `/crash/report` через реальный auth-обёрнутый роутер (oneshot + ConnectInfo loopback, паттерн `updater_routes.rs`). Сеть/бэкенд не нужны — temp-dir.
- **UI** (vitest): `CrashReportPrompt` состояния (idle→building→ready→error), **opt-in — ничего не зовётся до клика**, reveal/copy вызовы (мок fetch + `navigator.clipboard`).
- Тест-бинарники **не** называть с «crash»? — «crash» НЕ в списке Windows Installer Detection триггеров (install/setup/update/patch), 740 не грозит. Но перепроверить при первом прогоне; если внезапно — тот же `__COMPAT_LAYER=RunAsInvoker`.

## Критерии готовности (DoD)

1. На `kernelStage === 2` баннер предлагает opt-in отчёт; до клика ничего не собирается.
2. Клик → редактированный `crash-<ts>.txt` в `crash-reports/`; «Открыть папку» и «Копировать» работают.
3. `redact()` маскирует все документированные классы; анти-false-positive зелёный.
4. Все существующие гейты зелёные (kernel/updater/ui/core_loop не тронуты), новые crash-тесты зелёные, CI зелёный. Ноль изменений в поведении существующих роутов/баннера кроме добавленной секции.

## Out of scope (v1)

- Rust-паники шелла (нативный краш, webview мёртв) — отдельный будущий трек (panic hook + нативный диалог).
- Авто-отправка / серверный сток (Supabase/Sentry) — противоречит локальному стоку и minimalism.
- GPU-проба (логи backend'а и так несут CUDA/device в хвосте).
- Хранимое согласие / «не спрашивать снова» (per-crash opt-in, YAGNI).
- Android/macOS.
