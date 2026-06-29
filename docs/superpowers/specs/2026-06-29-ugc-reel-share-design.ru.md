# KALI — UGC Reel Share (рендер 9:16 голос-видео на бэкенде) — Дизайн-спека

**Дата:** 2026-06-29
**Статус:** Дизайн — ждёт spec-review + одобрения Vasily → writing-plans
**Якорь:** Конкурентная дифференциация против OpenHuman. Нить UGC-loop polish (выбрана вместо KALI-Super-Context, который идёт отдельным циклом).

> Это русская версия. Канонический английский оригинал: [`2026-06-29-ugc-reel-share-design.md`](2026-06-29-ugc-reel-share-design.md). При расхождении — английский первичен (его читает spec-reviewer / implementer).

---

## 1. Зачем это и зачем сейчас (grounded конкурентное обоснование)

Grounded-разбор OpenHuman (`tinyhumansai/OpenHuman`, ~33 758★ — верифицировано через GitHub API; Product Hunt top-post badges — **не** подтверждённое GitHub «#1 trending»; полный разбор: workflow `wf_991efc94-e56`, 2026-06-29) установил, с доказательствами из authenticated `gh` code-search:

- **Super Context — реальный shipped-код** (суб-агент `context_scout`, полный стек) — дать им должное; KALI не может объявлять это зазором.
- **Voice-authored создание агента для non-tech: ОТСУТСТВУЕТ** (`gh search 'agent builder OR createAgent'` = 0). Голос — только I/O.
- **UGC create→share→install loop: ОТСУТСТВУЕТ** (hard zeros по `reel/tiktok/ugc/shareAgent/import_agent`). Их единственная вирусная механика — реферал-код-за-кредит на залогиненном managed-backend; их «маркетплейс» — agent-to-agent крипто-коммерция. Ни то ни другое не есть «создал агента → поделился рилом → друг поставил».
- **Mobile: только scaffold**, нет shipped-приложения; heavy-local Tauri-mobile, не consumer UGC-поверхность.

**Вывод:** UGC-loop — единственная подлинно незанятая ось moat KALI. У KALI уже есть *проводка* loop (голос-билд → export-бандл → `kali://import` deep-link → install → callable; share-card PNG; вкладка «Сообщество»). Чего не хватает для **неотразимости** — самого share-артефакта: сегодня KALI шарит **статичную PNG-карточку**. На TikTok/Reels статичная картинка не расходится — расходится короткое **видео агента в действии, его собственным голосом**. Этот voice-in-action артефакт — ровно то, что OpenHuman структурно повторить не может (нет creation-by-voice).

Эта спека превращает share-артефакт из статичной карточки в **шаблонный 9:16 MP4 рил**, который проигрывает голос агента.

---

## 2. Цели / Не-цели

### Цели
- Созданный агент можно расшарить как короткий (~10–15с) вертикальный 9:16 MP4, в котором агент **говорит авто-сгенерированную интро-строчку своим голосом**, поверх анимированной карточки (waveform + burned-субтитры), с финальным кадром «сканируй, чтобы установить», несущим существующую self-contained import-ссылку/QR.
- Рендер переиспользует то, что уже в инсталлере (F5/ElevenLabs TTS, LLM router, libav* FFmpeg DLL) — **никакого нового тяжёлого бинаря, никакой GPL-эскалации**.
- Честная, мягкая деградация: любой сбой → фоллбэк на существующую PNG-карточку, затем на текст+ссылку. Без фейк-успеха, без краша.
- Рил генерится на **десктоп-подключённом бэкенде креатора**; **друг не рендерит ничего** (смотрит рил и тапает install).

### Не-цели (YAGNI — явно вне scope)
- On-device (Flutter) рендер видео. (Обходит заархивированный/GPL `ffmpeg_kit_flutter` trap; отложено вместе со standalone-mobile движком, master-plan WS-4.7.)
- Mascot / talking-head / lip-sync аватар.
- Пер-агентные кастомные голоса (голос — глобальная персона Jarvis, `VoiceConfig.tts_voice`).
- Редактируемый креатором скрипт рила (авто-интро фиксирован для v1).
- Deferred-deep-link путь друга «install → авто-импорт именно того агента» (отдельное слабое звено UGC; отслеживается, не строится тут).
- Изменения формата import-ссылки / caption / хэштегов (`ShareConfig` остаётся единым источником истины).

---

## 3. Архитектура и компоненты

### 3.1 Новый бэкенд-модуль — `kernel/reel/generator.py`
Чистые, тестируемые функции (каждая ≤50 строк; файл ≤800):

```python
async def build_intro_line(name: str, description: str, router: LLMRouter) -> str:
    """One-shot LLM-вызов → одна короткая RU интро-фраза
    («Привет, я {name}. Я умею {…}»). При ЛЮБОМ сбое LLM — вернуть
    детерминированную шаблонную строку из name+description (никогда не raise)."""

def synthesize_voice_clip(text: str) -> tuple[np.ndarray, int]:
    """Делегирует в kernel.voice.tts_router.generate_audio(text), затем
    НОРМАЛИЗУЕТ: каст в float32 и downmix в mono. `generate_audio`
    гарантирует только `np.ndarray` — dtype/channel layout НЕ контрактно
    float32-mono для F5 vs ElevenLabs, поэтому нормализуем здесь, чтобы дать
    waveform-envelope + audio-mux логике стабильный вход. Возвращает
    (float32 mono audio, sample_rate)."""

def compose_reel(
    audio: np.ndarray, sr: int, *, title: str, subtitle: str,
    intro_text: str, link: str, out_path: Path,
) -> Path:
    """Рендерит 9:16 MP4 в out_path через PyAV (`av`) поверх связанных
    libav* библиотек. Кадры растрятся через Pillow:
      (a) title-карточка (имя агента + описание),
      (b) waveform-пульс по огибающей амплитуды аудио, intro_text как
          burned-субтитры,
      (c) финальный кадр «Сканируй, чтобы установить» с QR ссылки `link`.
    Аудио муксится как AAC/PCM-дорожка; видео энкодится H.264 через
    libopenh264. Raise при сбое энкода (caller мапит в honest error)."""

async def generate_reel(name: str, *, registry, router, out_dir: Path) -> Path:
    """Оркестратор: резолв метаданных агента → интро-строчка → голос-клип →
    compose_reel. Возвращает путь к MP4."""
```

**Решение по кодеку (закрывает флагнутый риск):** H.264 через **libopenh264** (Cisco; BSD-лицензированная обёртка, роялти покрыты дистрибуцией бинаря Cisco). Это держит проприетарный инсталлер **LGPL-чистым** и **не** усугубляет существующий FFmpeg-GPL гейт (нет `libx264`/`--enable-gpl`). Контейнер MP4, faststart для соц-плеера. (Рассмотрено и отклонено: `libx264` — GPL-эскалация; `mpeg4` part 2 — LGPL-чисто, но хуже совместимость с соц-плеерами.)

### 3.2 Бэкенд-роут — `kernel/main.py`
Зеркалит существующий паттерн `GET /skills/{name}/export` (сейчас ~main.py:2442):

```python
@app.get("/skills/{name}/reel")
async def skills_reel(name: str):
    # 1. резолв dir/метаданных агента: SkillsRegistry.get(name) →
    #    фоллбэк plugin_registry.skill_dir_for(name)  (как в export)
    # 2. переиспользовать lowercase-latin gate валидации имени из export
    # 3. построить каноническую import-ссылку через общий helper из export
    # 4. generate_reel(...) → FileResponse(path, media_type="video/mp4")
    # 5. при ЛЮБОМ сбое → JSON {"status":"error","name":name,"message":...}
    #    (honest-fail; HTTP 200 с error-конвертом, как в export)
```

### 3.3 Мобайл — `mobile/lib/presentation/share_to_reels_screen.dart`
- `_prepare()` уже забирает export-бандл и строит ссылку. Добавить: после готовности ссылки дёрнуть `GET /skills/{name}/reel`; если вернулся `video/mp4` — сохранить во temp-файл и запомнить путь.
- `_share()` шарит `files: [<mp4>]` при наличии; **fallback-цепочка**: reel MP4 → существующая рендеренная PNG-карточка (`_renderCardPng`) → текст + caption-embedded ссылка. Ссылка, caption, хэштеги и on-screen QR не трогаем.
- **Ветвление по content-type (явно):** успешный путь `/reel` — бинарный `video/mp4` (`FileResponse`), сбой — JSON error-конверт. Мобильный клиент ОБЯЗАН ветвиться по `content-type` ответа (бинарь vs JSON) — не парсить JSON вслепую. Не-`video/mp4` (или error-статус) → триггер PNG-фоллбэка.
- Новый UI-элемент минимален: существующая кнопка шаринга теперь даёт видео; показать короткий статус «Собираю рил…» пока `/reel` в полёте (переиспользовать `_loading`/`shareLoading` копию).

### 3.4 Зависимости и влияние на дистрибуцию
- Добавить Python-deps: `av` (PyAV — связывает семейство libav*), `Pillow` (растр кадров) и `qrcode` (server-side QR-растр для финального кадра). QR-dep — **жёсткое добавление**: на бэкенде нет существующего server-side QR-растра (`qr_flutter` мобайла — client-only, тут не переиспользуем).
- Wheel'ы PyAV несут свои LGPL FFmpeg-библиотеки; убедиться, что кодек openh264 доступен wheel'у (стейджить Cisco `openh264` DLL в `premium_stage` через скриптованный staging-шаг — `build_installer_premium.bat`, `robocopy /E`, не `/MIR`).
- **Инсталлер надо пересобрать**, чтобы фича работала живьём (согласуется с существующей пометкой про устаревший инсталлер). Дельта размера (~десятки МБ за PyAV) — мерить на build-verify проходе.

---

## 4. Data flow

```
mobile: тап «Поделиться»
  → GET /skills/{name}/reel
      → резолв агента (name, description) + построить import-ссылку (форма ShareConfig)
      → build_intro_line  (LLM one-shot; шаблон-фоллбэк)
      → synthesize_voice_clip  (tts_router: F5 локально / ElevenLabs фоллбэк)
      → compose_reel  (Pillow-кадры + PyAV/libopenh264 энкод + audio mux)
      → FileResponse(video/mp4)
  → сохранить MP4 во temp → OS share sheet (видео + caption с kali://import ссылкой)
друг в TikTok/Reels
  → тапает ссылку → (приложение стоит) deep-link import / (не стоит) landing → store → install
  → импортированный агент LLM-callable  (существующий Phase A loop)
```

---

## 5. Обработка ошибок (честная деградация)

| Точка сбоя | Поведение |
|---|---|
| Неизвестное / не-шарабельное имя агента | Роут отдаёт `{status:"error", message}` (тот же gate, что export); мобайл показывает export-failed копию. |
| Сбой генерации LLM-интро | `build_intro_line` отдаёт детерминированную шаблонную строку; рил всё равно рендерится. |
| TTS недоступен / raise | Роут отдаёт honest error; мобайл фоллбэчит на PNG-карточку. |
| Сбой PyAV/энкода | Роут отдаёт honest error; мобайл фоллбэчит на PNG-карточку. |
| `/reel` таймаут / сеть | Мобайл фоллбэчит на PNG-карточку, затем текст+ссылку. |

Ни один путь не выдаёт success-статус для no-op. Никакой 500-краш не доходит до юзера.

---

## 6. Стратегия тестирования

**Python e2e (`-m core_loop`, ML-free, бежит в CI/секунды):**
- `tests/e2e/test_core_loop_reel_share.py`:
  - Mock LLM существующим `_StubRouter` (отдаёт интро-строку); mock TTS через `monkeypatch` — возврат крошечного синтетического ndarray + sr (без torch/F5).
  - Запустить **реальный PyAV-энкод** на ~1с клипе (wheel'ы PyAV self-contained, поэтому CI не нужен system FFmpeg).
  - Assert: HTTP 200; `content-type: video/mp4`; непустое тело; probe вывода = ровно 1 video-stream + 1 audio-stream; длительность в ожидаемом диапазоне; использованный энкодер — сконфигурированный H.264 (libopenh264).
  - Honest-fail тест: неизвестный агент → JSON error-конверт, статус 200, без исключения.
  - Fallback тест: TTS raise → роут отдаёт error-конверт (мобильная сторона фоллбэка покрыта Flutter-тестом).
- Юнит-тесты для `build_intro_line` шаблон-фоллбэка (LLM raise → детерминированная строка) и `compose_reel` (выдаёт валидный MP4 из фикс. крошечного аудио-буфера).

**Flutter widget-тест:** `/reel` вернул mp4 → share вызван с видео-файлом; `/reel` ошибка → share фоллбэчит на PNG-путь. (Бежать на `kali_test_34` по mobile-E2E memory; не на корраптящем `Pixel_7` AVD.)

**Ручной/живой (отложено в консолидированный live-verify проход):** пересобрать инсталлер → создать агента голосом → расшарить → подтвердить, что реальный MP4 со слышимым голосом Jarvis играет в соц-приложении; существующий two-device import loop не изменён.

---

## 7. Anti-pivot чек ✓

- Входы — **только KALI-native**: имя/описание самого агента и глобальный голос Jarvis. Ноль OAuth, ноль сторонних интеграций, никакой life-aggregation. Не дрейфует к 118-интеграционной / OS-ассистент DNA OpenHuman.
- Усиливает две не-копируемые оси (voice-authored creation + UGC share loop), не их поле.
- Переиспользует существующий self-contained `kali://import` / https deep-link (никакого нового формата дистрибуции); `ShareConfig` остаётся единым источником истины.

---

## 8. Риски и открытые пункты

- **Размер бандла / сборка:** PyAV + openh264 добавляют к и так большому инсталлеру; мерить на build-verify. Митигейшн: PyAV нужен только на десктоп (креатор) стороне.
- **Получение openh264:** подтвердить, что бинарь Cisco openh264 резолвится wheel'ом PyAV на целевой Windows-сборке; если нет — staging-шаг тянет/стейджит его. (Юр-пометка: роялти openh264 покрыты дистрибуцией Cisco; задокументировать bundled license-текст — согласуется с существующей FFmpeg license-text задачей.)
- **Латентность рендера:** ~12с рил должен энкодиться за несколько секунд на машине креатора; показать прогресс, выставить таймаут мобильного клиента, фоллбэк на таймауте.
- **Доступность голоса офлайн:** если ни F5 (GPU), ни ElevenLabs (ключ/сеть) недоступны — нет голос-клипа → honest фоллбэк на PNG. Приемлемо для v1.

---

## 9. Out-of-scope follow-ups (отмечено, не строится тут)
- Deferred-deep-link путь друга (install → авто-импорт тапнутого агента) — другое слабое звено UGC.
- Глубина engagement «Сообщества» (remix, creator-профили, trending-лента).
- SKILL.md «работает везде» interop-доказательство.
- KALI-Super-Context на локальных агентах/голос-истории (отдельный брейншторм-цикл).
