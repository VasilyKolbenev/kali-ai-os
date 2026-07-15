# Crash opt-in (Track4 #2) — Design

> **Дата:** 2026-07-14 · **Статус:** утверждён Vasily (подход A: HTTP `/crash/*` на :3006 + opt-in промпт); ревью-правки r2 (переделан триггер, закрыты reveal-инъекция, path-резолв, редакция).
> **Binding-ограничения Vasily:** (1) **без хардкода** — пути через существующий механизм данных-директории, паттерны редакции/пороги = именованные константы; (2) **ничего не ломать** — только аддитивно, все существующие тесты остаются зелёными.

## Контекст (как краши всплывают сегодня)

- Десктоп-шелл (`kali-desktop.exe`) спавнит `kali-backend.exe` дочерним; stdout/stderr → `%APPDATA%/KALI/logs/kali-backend.out.log` и `.err.log` (`lib.rs:51,62-67`, через `runtime_data_dir()` = `APPDATA/KALI`).
- **Rust axum control-plane на 127.0.0.1:3006 — отдельный `std::thread` десктоп-шелла** (`lib.rs:246` → `serve()`), живёт независимо от Python-дочки на :3005. `/health` на :3006 Rust отдаёт нативно; Python-роуты Rust проксирует и возвращает `upstream_unavailable`/BAD_GATEWAY когда Python мёртв (`http.rs:88-97,121-130`).
- **ВАЖНО (исправление r1):** `kernelStage`/красный баннer завязаны на WebSocket к **:3006** (`websocket.ts:42,88` → `setKernelConnected`), НЕ к Python. При смерти Python WS к живому :3006 держится → `kernelStage` НЕ доходит до 2 → тот баннер НЕ годится как триггер. `kernelStage===2` = мёртв сам Rust (тогда и crash-эндпоинты, и webview мертвы). Поэтому триггер — отдельный сигнал (ниже).
- Логи лежат локально; Vasily собирает их с друзей вручную.

## Что строим (подход A)

Opt-in: **на краше ничего не собирается/не отправляется, пока юзер не нажал кнопку.** Сток локальный — юзер сам передаёт .txt (Telegram/почта). Совместимо с [[feedback-app-minimalism]] (разовое согласие при аварии, не постоянная инструментация), снимает юр-риск отправки данных без юрлица.

## Триггер (переделан r2): «Rust жив, Python мёртв»

Новый эндпоинт **`GET /crash/status`** на :3006: Rust коротким пробом Python `/health` отвечает `{ backend_alive: bool }`. Раз эндпоинт ответил — :3006 жив, значит `/crash/report` тоже достижим (нет противоречия r1).

**ОБЯЗАТЕЛЬНО — явный таймаут (иначе виснет на зависшем Python):** `proxy::proxy_get_json` использует `Client::new()` БЕЗ timeout (`proxy.rs`). Мёртвый Python (порт закрыт) → send() падает быстро (loopback RST) — ок; но **зависший** Python (принял TCP, не отвечает) → хендлер повис бы, а 5-сек поллинг копил бы запросы. `/crash/status` ДОЛЖЕН оборачивать проб в `tokio::time::timeout(Duration::from_secs(2), …)` ИЛИ бить своим `reqwest …​.timeout(2с)` (прецедент — `updater.rs:353` ставит `.timeout(15с)` per-request). НЕ звать `proxy_get_json` голым.

UI-хук `useBackendLiveness` поллит `/crash/status` каждые `CRASH_POLL_MS` (=5000). Промпт показывается когда `backend_alive===false` **`CRASH_DOWN_STREAK` (=3) раз подряд** (~15с дебаунс — покрывает медленный старт Python, где `wait_for_backend_ready` даёт 5с; исключает транзиентные блипы). Сброс стрика на любом `true`. Если сам `/crash/status` недоступен (fetch reject = :3006 мёртв) — НЕ показываем промпт (Rust мёртв → webview всё равно нежилец, вне скоупа). Промпт монтируется тем же образом, что баннеры в `App.tsx` (fixed-оверлей), рядом с существующим `kernelStage`-блоком, **не меняя** его логику.

**Шум поллинга vs диагностика (осознанный trade-off):** проб `/health` каждые 5с пока Python ЖИВ засоряет его request-лог `/health`-строками — но захватываемый отчёт включает `.err.log` (stderr), куда идут трейсбеки/паники, а `/health`-access обычно в stdout/INFO. То есть настоящая причина краша в `.err.log` не вытесняется поллинг-шумом из `.out.log`. Приемлемо для v1; Rust-push по WS вместо поллинга — возможная будущая оптимизация (но это Rust-монитор+bus-событие+ws.rs — больше поверхности, против «ничего не ломать»).

## Компоненты и файлы

| Компонент | Файл | Ответственность |
|---|---|---|
| Редактор + сборщик (Rust) | `src-tauri/src/backend/crash.rs` (NEW) | `redact(&str)->String`, `build_report(logs_dir, reports_dir, meta)->Result<CrashReport>`, `reveal_reports_dir(reports_dir)->Result<()>`, `crash_paths()->(logs_dir, reports_dir)`; чисто/тестируемо |
| Роуты | `src-tauri/src/backend/http.rs` (modify) | `GET /crash/status`, `POST /crash/report`, `POST /crash/reveal` — аппенд как `/updater/*` (без смены сигнатуры `router_full`) |
| Loopback-гейт | `src-tauri/src/backend/auth.rs` (modify) | `is_loopback` → `pub(crate)`; хендлер `/crash/reveal` гейтит через `ConnectInfo` (см. §reveal). `/crash/status`+`/crash/report` — обычный loopback-exempt |
| Модуль | `src-tauri/src/backend/mod.rs` (modify) | `pub mod crash;` (алфавитно) |
| UI-промпт | `ui/src/components/CrashReportPrompt.tsx` (NEW) | локальный state `idle→building→ready→error` + `useBackendLiveness` |
| Монтаж | `ui/src/App.tsx` (modify) | вставить `<CrashReportPrompt/>` рядом с `kernelStage`-оверлеем (аддитивно) |
| Endpoints | `ui/src/api/endpoints.ts` (modify) | +3 записи `RUST_ENDPOINTS` (GET /crash/status, POST /crash/report, POST /crash/reveal) |

## Пути (без хардкода, БЕЗ ловушки %LOCALAPPDATA%)

`runtime_data_dir()` — приватная fn бинарь-крейта `lib.rs`, из `crash.rs` (lib-крейт `kali_desktop::backend`) НЕ видна. `crash.rs::crash_paths() -> Result<(logs_dir, reports_dir)>` резолвит сам через **`dirs::data_dir()`** (Windows roaming = `%APPDATA%` → совпадает с lib.rs и прецедентом `auth.rs`), НЕ `data_local_dir()` (это `%LOCALAPPDATA%` — куда смотрит `updater::updates_dir()`; копировать его сюда = читать НЕ ту папку и не найти логов). `logs_dir = data_dir()/KALI/logs`, `reports_dir = data_dir()/KALI/crash-reports` (`create_dir_all`). **Возвращает `Result` (НЕ tuple):** `dirs::data_dir()` может дать `None` (APPDATA не задан — dev-only) → `/crash/report` отвечает 500, а НЕ паникует на axum-воркере. (Dev-фолбэк lib.rs на exe-relative здесь не воспроизводим — приемлемо.)

## Поток

1. `useBackendLiveness` видит Python down (стрик 3) → рендер промпта: «Похоже, ядро аварийно остановилось. Подготовить отчёт для разработчика, чтобы починить?» + `[Подготовить отчёт]`. До клика — ничего.
2. Клик → `POST /crash/report` (тело `{reason?}`, опц.). Rust: `crash_paths()` → читает последние `CRASH_LOG_TAIL_LINES`(=400) строк из `.err.log` и `.out.log` (каждый свой хвост); мета `version`(`CARGO_PKG_VERSION`), `os`/`arch`(`std::env::consts`), `ts`(`chrono::Utc::now()`), `reason`; всё через `redact()`; итог капается `CRASH_REPORT_MAX_BYTES`(=256 KB) — **режется по СТАРШЕМУ краю (сохраняем свежий хвост) с маркером `…(обрезано)`**; пишет `reports_dir/crash-<ts>.txt`; возвращает `{ path, text }`.
3. UI: путь + свёрнутое превью (первые ~30 строк `text`) + `[Открыть папку]` (→ `POST /crash/reveal`, **тело пустое**) + `[Копировать текст]` (`navigator.clipboard.writeText(text)`, webview, без tauri).
4. Юзер тащит .txt в чат Васе / вставляет текст.

**Формат** (читаемый .txt = прозрачность):
```
KALI crash report
version: 1.0.0-rc1
os: windows / x86_64
time: 2026-07-14T16:40:00Z
reason: <reason или ->

--- kali-backend.err.log (последние 400 строк, отредактировано) ---
<redacted tail>

--- kali-backend.out.log (последние 400 строк, отредактировано) ---
<redacted tail>
```

## Редакция (safety-critical — точные анкерованные паттерны, r2)

Последовательность проходов, **консервативно (лучше пере-замаскировать)**; все regex — именованные константы. Порядок: (1) префикс-ключи → (2) Bearer/Authorization → (3) assignment (только `=`) → (4) длинные руны → (5) email → (6) Windows-путь. (Ключи ДО путей, чтобы path-маскировка не съела токен.)

| # | Класс | Точный паттерн (анкерованный) | Замена |
|---|---|---|---|
| 1 | OpenAI/Anthropic/DeepSeek | `\bsk-(ant-\|proj-)?[A-Za-z0-9_-]{20,}\b` | `***REDACTED***` |
| 1 | Google | `\bAIza[0-9A-Za-z_-]{35}\b` | `***REDACTED***` |
| 1 | JWT | `\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*` | `***REDACTED***` |
| 2 | Bearer | `(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+` | `Bearer ***REDACTED***` |
| 2 | Authorization | `(?i)\bauthorization:\s*.+` | `Authorization: ***REDACTED***` |
| 3 | Assignment (=, значение с опц. кавычкой) | `(?i)\b(api[_-]?key\|token\|secret\|password\|passwd\|pwd)\s*=\s*["']?[^\s"']{6,}` | `$1=***REDACTED***` |
| 3 | Conn-string с паролем | `(?i)\b([a-z][a-z0-9+.-]*)://([^:@\s]*):[^@\s]+@` | `$1://$2:***@` |
| 4 | Hex-руна | `\b[0-9a-fA-F]{32,}\b` | `***REDACTED***` |
| 4 | base64-руна | `\b[A-Za-z0-9+/]{40,}={0,2}\b` | `***REDACTED***` |
| 5 | Email | `\b[\w.+-]+@[\w-]+\.[\w.-]+\b` | `***@***` |
| 6 | Windows user-путь | `(?i)([a-z]:[\\/]users[\\/])[^\\/\s]+` | `$1<user>` |

**Анти-false-positive (обычные слова/пути НЕ трогаем — анкеровка `\b` + charset/длина это обеспечивают):** `disk cache`, `task exception`, `desktop`, `flask`, `token count: 512` (нет `=`), `C:\Program Files\KALI\models` (не `\users\`). **Приемлемый over-mask (документируем, НЕ баг):** 40-hex git-SHA и длинные base64-блобы (data:/картинки) маскируются руной 4 — безопаснее, чем пропустить секрет; .txt остаётся читаемым.

**Правки после ревью плана (r3, эмпирически проверены — НЕ откатывать):**
- **Authorization = `.+`, НЕ `\S+`** (строка выше уже исправлена). `\S+` съедал только `Authorization: Basic`, оставляя сам credential открытым: base64 от `user:pass` часто <40 символов → руна класса 4 его не ловит = **утечка**. `.` не матчит `\n` → маскируется ровно значение заголовка, следующие строки лога целы.
- **`%USERPROFILE%` не маскируем** — литеральный плейсхолдер имени пользователя не содержит; раскрытый путь ловит паттерн класса 6.
- **Проб мёртвого порта НЕ мгновенный** (посылка §Триггер была неточной): замерено на машине Vasily — закрытый loopback-порт отдаёт `ConnectionRefused` за ~2.02–2.06с (вероятно, из-за защитного софта), т.е. срабатывает 2с-таймаут, а не RST. Функционально безвредно: 2с < 5с интервала поллинга, накопления запросов нет.

**Честная граница:** редакция = defense-in-depth, НЕ гарантия. Два предохранителя: (1) .txt читаемый, юзер видит что отправляет (человеческий финальный гейт); (2) сток локальный — отправка только по решению юзера.

## `/crash/reveal` — без инъекции (r2)

Клиент **не передаёт путь**. Rust открывает известную `reports_dir` целиком (папку), не `explorer /select,<file>` (уходим от запятая/пробел-парсинга и от произвольного reveal). Реализация: `std::process::Command::new("explorer").arg(&reports_dir)` (или `opener`-крейт если уже в графе — иначе explorer напрямую).

**Loopback-гейт — точная разводка (r2):** `is_loopback` — приватная fn `auth.rs:150`. Роуты crash регистрируются в `http.rs::router_full` (не в `with_auth`), поэтому гейтим **в самом хендлере**: сделать `auth::is_loopback` → `pub(crate)`, хендлер `/crash/reveal` берёт `ConnectInfo<SocketAddr>` (доступен — `serve()` использует `into_make_service_with_connect_info`; тесты инжектят вручную как `updater_routes.rs:34`) и при не-loopback пире отвечает 403. `/crash/status` и `/crash/report` — обычные (loopback-exempt через существующий auth-слой, как `/updater/*`).

## Ошибки

| Сценарий | Поведение |
|---|---|
| Логи-папка/файлы нет или пусты | Отчёт только с метой + строка «логи не найдены»; НЕ падаем, `/crash/report`=200 |
| Запись отчёта не удалась | `/crash/report`=500 `{error}`; UI: «Не удалось собрать отчёт» + подсказка открыть папку логов вручную |
| `reveal` упал | `/crash/reveal`=500; UI показывает путь текстом |
| `/crash/status` reject (Rust мёртв) | Промпт НЕ показываем (вне скоупа) |
| Всегда | Ноль авто-сбора/авто-отправки — только по клику |

## Тесты (TDD)

- **Rust** (`src-tauri/tests/crash_redact.rs`, `crash_report.rs`, `crash_routes.rs`): `redact()` — по каждому классу 1-6 позитив + **анти-FP негативы** (перечислены выше, каждый как явный assert «не изменилось») + комбо-строка со всеми классами; `build_report` (хвост N строк, отсутствующие/пустые логи→мета-only, cap по байтам режет старший край + маркер, порядок секций); smoke `/crash/status`(`{backend_alive}`) и `/crash/report` через реальный auth-обёрнутый роутер (oneshot + ConnectInfo loopback, как `updater_routes.rs`) — **`to_bytes(res, CRASH_REPORT_MAX_BYTES*2)`** (не 64 KB — отчёт до 256 KB). Сеть/бэкенд не нужны — temp-dir + инъекция путей в `build_report`.
- **UI** (vitest): `CrashReportPrompt`/`useBackendLiveness` — стрик-дебаунс (3 down→показать, 1 up→скрыть), opt-in (`/crash/report` НЕ зовётся до клика), состояния idle→building→ready→error, reveal/copy (мок fetch + `navigator.clipboard`).
- Имя тест-бинарников: «crash» НЕ в триггерах Windows Installer Detection (install/setup/update/patch) → error 740 не грозит; перепроверить при первом прогоне, при сюрпризе — `__COMPAT_LAYER=RunAsInvoker` (как updater).

## Критерии готовности (DoD)

1. Промпт появляется когда Python мёртв (стрик 3) И :3006 жив; до клика ничего не собирается.
2. Клик → редактированный `crash-<ts>.txt` в `crash-reports/`; «Открыть папку» (без клиентского пути) и «Копировать» работают.
3. `redact()` маскирует классы 1-6; анти-FP негативы зелёные; over-mask задокументирован.
4. `/crash/reveal` loopback-only, без клиентского пути. Пути через `dirs::data_dir()` (не local).
5. Все существующие гейты зелёные (kernel/updater/ui/core_loop не тронуты), новые crash-тесты зелёные, CI зелёный. Существующие роуты/баннер/WS-логика без изменений поведения.

## Out of scope (v1)

- Rust-паники шелла (webview мёртв) — отдельный трек (panic hook + нативный диалог).
- Авто-отправка / серверный сток (Supabase/Sentry) — против локального стока и minimalism.
- GPU-проба (логи backend'а несут CUDA/device в хвосте).
- Хранимое согласие / «не спрашивать снова» (per-crash opt-in, YAGNI).
- AWS/прочие облачные ключ-форматы (у KALI нет AWS; локальный SQLite) — низкая вероятность.
- Android/macOS.
