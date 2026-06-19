# UGC Share Loop — agents/skills → Reels/TikTok/YouTube → friends install

**Status:** spec (2026-06-19). Drives the mobile `Share-to-Reels` feature (plan
item #21) and the desktop equivalent.
**Anti-pivot anchor:** publishing uses the **OS native share sheet**, never
per-platform OAuth/API. We are not building an SMM tool.

## Goal
Close the viral loop that distribution depends on:
> создал агента голосом → поделился роликом → друг увидел → поставил KALI →
> получил **именно этого** агента в один тап.

## The core clarity — это ДВЕ разные задачи
Смешивать их — главная причина путаницы («как связать с профилями соцсетей?»).

### Problem A — публикация ролика (создатель → его соцсеть)
**Связка с профилями TikTok/IG/YT НЕ нужна. Сознательно.**
- KALI отдаёт готовый артефакт (видео/картинка/файл + подпись) в **нативный
  share sheet** ОС (`Share.shareXFiles`/`Share.share`).
- ОС показывает установленные приложения; пользователь постит **под своим
  аккаунтом, где уже залогинен**. KALI не видит логинов/токенов.
- **Почему не official API:** TikTok Content Posting / Instagram Graph / YouTube
  Data API требуют dev-приложение, OAuth, ревью платформы (недели-месяцы),
  бизнес-верификацию, комплаенс. До-PMF это смерть в бюрократии + хранение
  чужих токенов = дыра безопасности. Native sheet = ноль одобрений, работает
  сегодня.

### Problem B — замкнуть петлю (зритель → ставит KALI → получает агента)
Видео инертно — агент не «проезжает» через пиксели. Нужен **обратный канал**:
1. В подписи/кадре — **CTA + короткая ссылка** и **QR** (QR надёжнее всего:
  подписи в TikTok/IG Reels **не кликабельны**, в YouTube — да).
2. Ссылка → **deep link** → KALI установлена? открыть с id агента : магазин →
  после установки deferred-link с id.
3. KALI ставит агента: из **каталога** (если опубликован) или из **бандла,
  встроенного в ссылку/файл** (P2P, без сервера).

«Профиль», который реально нужен, — это **KALI-профиль автора** в нашем
каталоге, НЕ профиль соцсети. Может стартовать анонимно (device id).

## Что УЖЕ есть на бэкенде (не greenfield)
Заземлено по `kernel/main.py`:
- `POST /skills/publish` (2032) — бандлит локальный скилл, safety-проверки,
  возвращает `bundle_path` + `catalog_repo_url` + `instructions`. **Не пушит**
  в GitHub сам.
- `POST /skills/install` (1909) — ставит из каталога по `source_id`+`name`.
- `POST /skills/validate` (1970), `GET /skills/installed`, `POST /skills/uninstall`.
- `GET /skills/catalog` (1877) + `/sources` + `/refresh` — GitHub-backed каталог
  с источниками и trust-уровнями. Это и есть «Сообщество».
- `POST /agents/create`, `GET /agents/custom` — пользовательские агенты.

**Вывод:** publish→catalog→install round-trip каркасно существует. Не хватает:
(1) автоматизации publish→repo (сейчас ручная submission); (2) deep-link слоя;
(3) install-from-bundle для P2P; (4) генерации ролика; (5) атрибуции.

## Architecture (MVP → scale)
- **Publish (A):** native share sheet. Инвариант, не зависит от остального.
- **Travel (B), две дорожки:**
  - **P2P-бандл (быстрый MVP, ноль серверов):** `/skills/publish` даёт бандл →
    делимся файлом/встроенной в QR/ссылку полезной нагрузкой → друг ставит
    локально. Хорош для маленьких голосовых агентов.
  - **Каталог (масштаб):** publish автоматизированно кладёт в `kali-skills`
    repo → ссылка `https://<domain>/a/<slug>` → друг ставит `/skills/install`.
    Нужен для discovery, больших агентов, атрибуции.
- **Import:** KALI регистрирует `kali://import?...` + App Links/Universal Links
  с домена лендинга → резолв → установка.

## No-hardcode config surface (обязательно)
Всё конфигурируемое — в одном месте, не магические строки по коду:
- `linkBase` (домен deep-link/лендинга) — App Links host.
- `androidStoreUrl`, `iosStoreUrl` — ссылки в магазины.
- `defaultHashtags`, шаблон подписи — через l10n, не литералы в виджетах.
- `catalogRepoUrl` — уже отдаётся бэкендом (`publish.catalog_repo_url`), не
  дублировать на клиенте.

## Implementation slices
**Slice 1 — реальный шеринг (mobile-only, без ребилда бэка) ← ЭТОТ заход**
- `share_plus` + `qr_flutter`.
- `core/share_config.dart` — единый конфиг (linkBase/store/hashtags).
- Честный экран вместо мокапа: реальный QR ссылки, превью, реальная кнопка →
  `Share.share(caption+link)`. Убрать фейк-лайки/«@kali_creator»/«Trending Audio»/
  SnackBar-only.
- Точка входа: кнопка «Поделиться» на карточке **установленного** агента.
- **Success:** на эмуляторе тап «Поделиться» открывает системный share sheet с
  реальным текстом+ссылкой; QR рендерится и сканируется; фейков нет.

**Slice 2 — импорт-петля (mobile + backend, нужен ребилд+рестейдж)**
- `app_links` + AndroidManifest intent-filters + iOS Universal Links.
- `kali://import?slug=…` (каталог) и `…?b=<base64url-gzip-bundle>` (P2P).
- Бэкенд: `POST /skills/install-bundle` (поставить из присланного бандла);
  опц. автоматизация `/skills/publish` → коммит в `kali-skills`.
- **Success:** свежий эмулятор по ссылке ставит конкретный агент end-to-end.

**Slice 3 — генерация ролика**
- Рендер карточки агента (RepaintBoundary→PNG) как MVP; видео (кадры→mp4) позже.
- **Success:** реальный файл-артефакт уходит в share sheet.

**Slice 4 — атрибуция**
- Ссылка несёт agent+creator id → счётчик установок на ролик → «твоего агента
  скачали N раз», лидерборд. Лёгкая identity автора.

## Decisions (нужен Vasily)
1. **Домен** лендинга/deep-link (App Links host): есть свой (kali.app?) или
  ставлю конфиг-плейсхолдер с пометкой «заменить»? Не блокирует Slice 1.
2. **Каталог-repo** для UGC: `github.com/VasilyKolbenev/kali-skills` (хэндофф уже
  просит создать) — подтвердить имя/видимость.
3. Порядок: P2P-бандл vs каталог первым в Slice 2 (реком. P2P — быстрее к
  работающей петле без серверной автоматизации).

## Honesty / market framing
- «Поделиться» становится реальным в Slice 1; авто-импорт конкретного агента —
  Slice 2. Не выдаём недостроенную петлю за готовую.
- Полный публичный UGC (атрибуция, лендинг, deferred deep links) — Slice 2-4,
  пост-демо.
