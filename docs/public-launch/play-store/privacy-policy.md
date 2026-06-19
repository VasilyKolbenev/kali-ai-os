# KALI Mobile — Privacy Policy / Политика конфиденциальности

> **STATUS: DRAFT for Google Play submission. Not yet legal counsel-reviewed.**
> Placeholders below in `<ANGLE_BRACKETS>` MUST be filled before publishing.
> This document describes the **KALI Mobile companion app** (`applicationId: ai.kali.mobile`).
> The desktop KALI application has its own separate terms.

- **App name:** KALI (Mobile Companion)
- **Package / applicationId:** `ai.kali.mobile`
- **Publisher / Data controller:** `<LEGAL_ENTITY_NAME>` (`<COUNTRY_OF_REGISTRATION>`)
- **Contact e-mail:** `<PRIVACY_CONTACT_EMAIL>` (a working address is required by Play; a personal mailbox is acceptable for a solo publisher)
- **Policy URL (must be publicly hosted before submission):** `<https://YOUR-DOMAIN/privacy>`
- **Effective date:** `<YYYY-MM-DD>`
- **Last updated:** 2026-06-19

---

## English

### 1. The short version (plain language)

KALI Mobile is a **remote control for the KALI app that runs on your own computer.** The phone app does not have a cloud of its own. There is no KALI account, no login, and no KALI server collecting your data.

- Your **voice and conversations** are sent to **your own PC** over your local network — not to us.
- Your data (conversations, agents, facts the assistant remembers) is **stored on your PC**, not in our cloud.
- We do **not** put any analytics, tracking, advertising, or crash-reporting SDK in this app. (Verified: the app's dependency manifest contains no Firebase, Sentry, Amplitude, or similar — `mobile/pubspec.yaml`.)
- The only data that ever leaves your devices for the open internet is data **you** trigger by connecting **your own** third-party API keys (for example an AI model or a cloud voice service). Those requests go directly from your PC to that provider, under that provider's terms.

On-device, local-first handling is the core design of KALI, not an afterthought.

### 2. What the app does

The KALI Mobile app connects to a copy of the KALI desktop application running on a computer you control, on the same local network (Wi‑Fi/LAN). You point the app at your computer's IP address; until you do, the app is not connected to anything (`mobile/lib/core/config.dart` — the server address defaults to empty).

Once connected, the app lets you:
- talk to your KALI assistant by voice (microphone audio is streamed to your PC);
- view a dashboard and the agents you have created;
- create/manage voice agents;
- share an agent you created with a friend using your phone's standard **Share** sheet.

### 3. What data the app handles, and where it goes

| Data | Why | Where it goes | Leaves the device for *our* servers? |
|---|---|---|---|
| **Microphone audio** (your speech) | To talk to your KALI assistant | Streamed over your local network to **your own PC** (the KALI desktop you connect to), as 16 kHz PCM audio. | **No.** It goes to your computer, not to us. |
| **Conversation text / transcripts, the agents you build, facts the assistant remembers** | Core assistant features | Stored in a database **on your PC** (the KALI desktop app). | **No.** This app keeps no account and uploads none of it to us. |
| **Your computer's local IP address** | So the app knows which PC to connect to | Kept **on the phone**, used only to open the local connection. | **No.** |
| **Third-party API keys** *(optional, only if you add them on your PC)* | To use an AI model or a cloud voice provider you chose | Used **on your PC** to call that provider directly. | **No** — and the key is entered on the desktop side, not in this mobile app. |

**Audio is not stored on the phone for our benefit and is not sent to us.** It is captured only while you are actively talking to the assistant, streamed to your own computer, and the stream stops when you stop talking (`mobile/lib/core/audio_recorder_service.dart`).

### 4. Data sent to third parties

The KALI Mobile app **itself** sends data to exactly one destination: **the KALI desktop you connect to on your own network.** It does not contain any third-party SDK that phones home.

Separately, **if you choose** to configure a third-party AI or voice provider (for example by entering your own API key on the desktop side), then **your PC** will send the relevant request (e.g. a transcript or a synthesis request) to **that provider you selected**, governed by that provider's privacy policy. KALI does not receive a copy. This is optional and under your control. Examples of providers KALI can use when you supply a key include large-language-model and cloud text-to-speech services; the specific provider is the one you pick.

We do **not** sell or share your personal data with data brokers. We do **not** use your data for advertising. We run **no** advertising SDK.

### 5. Network security note

For the local connection between the phone and your computer, the current build uses an **unencrypted** local-network channel (HTTP/WebSocket over your LAN; the app sets `usesCleartextTraffic` for this reason — `mobile/android/app/src/main/AndroidManifest.xml`). This traffic stays on your local network and is not routed through us. Because it is not yet encrypted in transit on the LAN, you should connect only on networks you trust (e.g. your home Wi‑Fi). `<TODO before public launch: state the plan for LAN encryption / pairing, or remove this caveat once addressed.>`

### 6. Permissions the app requests

The app requests only two Android permissions. Both are listed and justified in `permissions.md` in this same folder.

- **Microphone (`RECORD_AUDIO`)** — to let you talk to the assistant. Audio is streamed to your own PC; nothing is recorded for us. If you deny it, voice features are unavailable but the rest of the app still works (`audio_recorder_service.dart` returns "permission denied" and surfaces it to you).
- **Internet/Network (`INTERNET`)** — to reach the KALI desktop on your local network (and, only via your PC and only if you set it up, the third-party provider you chose).

The app does **not** request location, contacts, SMS, call logs, camera, photos, or background-location permissions.

### 7. Children

KALI Mobile is **not directed to children** and is intended for users `<13+ / 16+ / 18+ — choose your target audience for the Play "Target audience and content" form>`. We do not knowingly collect personal data from children.

### 8. Account, deletion, and your control

- There is **no KALI account** for the mobile app, so there is nothing for us to delete on a server — we hold nothing.
- Conversation history, agents, and remembered facts live on **your computer** (the KALI desktop app). You control them there; deleting the desktop app's data store removes them.
- Uninstalling the mobile app removes its local settings (such as the saved computer IP) from the phone.
- To ask a question about your data, contact `<PRIVACY_CONTACT_EMAIL>`.

> **Note for the Play "Data deletion" requirement:** Because the app keeps no server-side account, the data-deletion URL/flow should point users to (a) uninstalling the app and (b) clearing the desktop app's local data. Provide `<https://YOUR-DOMAIN/data-deletion>` (a simple page describing those two steps) if Play requires a dedicated deletion URL.

### 9. Changes to this policy

If this policy changes, we will update the date above and post the new version at the policy URL. Material changes will be reflected before they take effect.

### 10. Legal basis & regional notes

`<TODO with counsel: add GDPR lawful-basis statement (EEA), UK GDPR, and any CCPA/CPRA "we do not sell" confirmation as applicable to where you distribute. Given the local-first design, most processing happens on the user's own device under their control, but the controller relationship and contact obligations must still be stated correctly for your jurisdictions.>`

---

## Русский

### 1. Коротко и по-человечески

KALI Mobile — это **пульт управления приложением KALI, которое работает на вашем собственном компьютере.** У мобильного приложения нет своего облака. Нет аккаунта KALI, нет входа по логину, нет сервера KALI, который собирал бы ваши данные.

- Ваш **голос и переписка** отправляются на **ваш собственный ПК** по локальной сети — не нам.
- Ваши данные (диалоги, созданные агенты, факты, которые запоминает ассистент) **хранятся на вашем ПК**, а не в нашем облаке.
- Мы **не** встраиваем в это приложение аналитику, трекинг, рекламу или сбор отчётов о сбоях. (Проверено: в манифесте зависимостей приложения нет Firebase, Sentry, Amplitude и подобного — `mobile/pubspec.yaml`.)
- Единственные данные, которые вообще покидают ваши устройства и уходят в интернет, — это то, что вы сами инициируете, подключив **свои собственные** ключи сторонних сервисов (например, ИИ-модель или облачный голос). Эти запросы идут напрямую с вашего ПК к выбранному провайдеру, по его правилам.

Локальная обработка «на устройстве» — это основа KALI, а не дополнительная опция.

### 2. Что делает приложение

KALI Mobile подключается к настольному приложению KALI, запущенному на вашем компьютере, в той же локальной сети (Wi‑Fi/LAN). Вы указываете IP-адрес своего компьютера; пока вы этого не сделали, приложение ни к чему не подключено (`mobile/lib/core/config.dart` — адрес сервера по умолчанию пуст).

После подключения приложение позволяет:
- говорить с ассистентом KALI голосом (звук с микрофона передаётся на ваш ПК);
- смотреть дашборд и созданных вами агентов;
- создавать и настраивать голосовых агентов;
- поделиться созданным агентом с другом через **стандартное системное меню «Поделиться»**.

### 3. Какие данные обрабатывает приложение и куда они идут

| Данные | Зачем | Куда идут | Уходят ли на *наши* серверы? |
|---|---|---|---|
| **Звук с микрофона** (ваша речь) | Чтобы говорить с ассистентом | Передаётся по локальной сети на **ваш ПК** (настольный KALI), формат — PCM 16 кГц. | **Нет.** Идёт на ваш компьютер, не нам. |
| **Текст диалогов, созданные агенты, факты, которые запоминает ассистент** | Основные функции ассистента | Хранятся в базе данных **на вашем ПК**. | **Нет.** У приложения нет аккаунта, оно ничего нам не загружает. |
| **Локальный IP-адрес вашего компьютера** | Чтобы знать, к какому ПК подключаться | Хранится **на телефоне**, используется только для локального подключения. | **Нет.** |
| **Ключи сторонних сервисов** *(необязательно, только если вы их добавили на ПК)* | Чтобы использовать выбранную вами ИИ-модель или облачный голос | Используются **на вашем ПК** для прямого обращения к провайдеру. | **Нет** — и сам ключ вводится на стороне ПК, не в этом мобильном приложении. |

**Звук не сохраняется на телефоне в наших интересах и не отправляется нам.** Он записывается только пока вы активно говорите с ассистентом, передаётся на ваш компьютер, и поток прекращается, когда вы перестаёте говорить (`mobile/lib/core/audio_recorder_service.dart`).

### 4. Передача данных третьим лицам

**Само** приложение KALI Mobile отправляет данные ровно в одно место: на **настольный KALI, к которому вы подключаетесь в своей сети.** В нём нет сторонних SDK, которые «звонят домой».

Отдельно: **если вы сами** настроите сторонний сервис ИИ или голоса (например, введёте свой ключ на стороне ПК), тогда **ваш ПК** отправит соответствующий запрос (например, транскрипт или запрос синтеза) **выбранному вами провайдеру**, по его политике конфиденциальности. KALI копию не получает. Это по вашему выбору и под вашим контролем.

Мы **не** продаём и **не** передаём ваши персональные данные брокерам данных. Мы **не** используем ваши данные для рекламы и **не** встраиваем рекламные SDK.

### 5. О сетевой безопасности

Локальное соединение между телефоном и компьютером в текущей сборке использует **незашифрованный** канал в локальной сети (HTTP/WebSocket по вашему LAN; поэтому в приложении установлен `usesCleartextTraffic` — `mobile/android/app/src/main/AndroidManifest.xml`). Этот трафик остаётся в вашей локальной сети и не проходит через нас. Поскольку на уровне LAN он пока не шифруется, подключайтесь только в доверенных сетях (например, домашний Wi‑Fi). `<TODO к публичному запуску: описать план шифрования/сопряжения в LAN или убрать оговорку после доработки.>`

### 6. Какие разрешения запрашивает приложение

Приложение запрашивает только два разрешения Android. Оба перечислены и обоснованы в файле `permissions.md` в этой же папке.

- **Микрофон (`RECORD_AUDIO`)** — чтобы говорить с ассистентом. Звук передаётся на ваш ПК; для нас ничего не записывается. Если отказать — голосовые функции недоступны, остальное приложение работает.
- **Интернет/Сеть (`INTERNET`)** — чтобы подключаться к настольному KALI в локальной сети (и, только через ваш ПК и только если вы это настроили, к выбранному вами стороннему провайдеру).

Приложение **не** запрашивает геолокацию, контакты, SMS, журналы звонков, камеру, фото или фоновую геолокацию.

### 7. Дети

KALI Mobile **не предназначено для детей** и рассчитано на пользователей `<13+ / 16+ / 18+ — выберите целевую аудиторию для формы Play>`. Мы сознательно не собираем персональные данные детей.

### 8. Аккаунт, удаление и контроль

- У мобильного приложения **нет аккаунта KALI**, поэтому нам нечего удалять на сервере — мы ничего не храним.
- История диалогов, агенты и запомненные факты хранятся на **вашем компьютере** (настольный KALI). Вы управляете ими там; удаление хранилища настольного приложения удаляет их.
- Удаление мобильного приложения убирает его локальные настройки (например, сохранённый IP компьютера) с телефона.
- Вопросы по данным: `<PRIVACY_CONTACT_EMAIL>`.

### 9. Изменения политики

Если политика изменится, мы обновим дату выше и опубликуем новую версию по адресу политики.

---

### Verification notes (for the publisher — remove before hosting publicly)

Every factual claim above is grounded in the shipped mobile code:
- Only two permissions requested — `mobile/android/app/src/main/AndroidManifest.xml:2-3`.
- Mic audio is PCM 16 kHz mono, streamed over WebSocket to the user's PC, started only on demand and stopped on demand — `mobile/lib/core/audio_recorder_service.dart:22-57`.
- Connection target is the user-supplied PC IP on port 3006 over the LAN; defaults to none — `mobile/lib/core/config.dart:3`, `mobile/lib/core/websocket_client.dart:34`.
- Cleartext LAN traffic — `AndroidManifest.xml:7` (`usesCleartextTraffic="true"`).
- No analytics/crash/ad SDK in the app — `mobile/pubspec.yaml` (no Firebase/Sentry/Amplitude/PostHog dependency).
- Persistent user data (conversations, transcripts, facts, agents) lives in desktop-side SQLite, per install — `kernel/database.py:12-49`.
- UGC sharing uses the OS native share sheet, no platform OAuth — `mobile/lib/presentation/share_to_reels_screen.dart:100` (`SharePlus.instance.share`).
