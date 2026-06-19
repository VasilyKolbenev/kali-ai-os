# KALI Mobile — Google Play Store Listing

> **STATUS: DRAFT for Google Play submission.** Copy is bilingual (RU primary market, EN secondary).
> Character counts are checked against Play limits: **Title ≤ 30**, **Short description ≤ 80**, **Full description ≤ 4000**.
> Fill `<PLACEHOLDERS>` (graphics, contact, URLs) before submitting.

- **applicationId:** `ai.kali.mobile` (confirmed — `mobile/android/app/build.gradle.kts:22`)
- **Default language:** Russian (`ru-RU`); add English (`en-US`) as a second store locale.
- **App type:** Application (not a game).
- **Current version (mobile):** `0.1.0` (`mobile/pubspec.yaml:4`) — bump for the first public track as needed.

---

## Category & metadata

| Field | Value | Notes |
|---|---|---|
| **Application type** | App | |
| **Category** | **Productivity** | Primary. KALI Mobile is a companion/control for a productivity assistant. (Alternative: *Tools*.) |
| **Tags** | AI assistant, voice assistant, productivity, automation | Pick from Play's tag list at submission. |
| **Contact email** | `<PUBLISHER_CONTACT_EMAIL>` | Required, public on the listing. |
| **Website** | `<https://YOUR-DOMAIN>` | Optional but recommended; must resolve. |
| **Privacy policy URL** | `<https://YOUR-DOMAIN/privacy>` | Required. See `privacy-policy.md`. |
| **Content rating** | Complete the IARC questionnaire | Expected: *Everyone / 3+* (no objectionable content), but the questionnaire is authoritative. |
| **Ads** | **Contains no ads** | True — no ad SDK in `mobile/pubspec.yaml`. |
| **In-app purchases** | `<None at launch / declare if a Pro tier is wired into the mobile app>` | The Pro tier described in VISION.md is desktop-side; do NOT declare IAP on mobile unless billing is actually implemented in this app. |

---

## RU (primary)

### App title (≤ 30 chars)

```
KALI — голосовой ассистент
```
*(26 characters incl. spaces.)*

> Alternatives if you prefer the brand-only form: `KALI` (4) or `KALI Mobile` (11).

### Short description (≤ 80 chars)

```
Голосовой ИИ-ассистент. Создавай агентов голосом. Данные — на твоём ПК.
```
*(70 characters.)*

### Full description (≤ 4000 chars)

```
KALI — голосовой ИИ-ассистент, которым вы управляете с телефона, а вся работа идёт на ВАШЕМ компьютере.

Это приложение — компаньон к настольному KALI. Вы запускаете KALI на своём ПК, подключаете телефон к нему по домашней сети — и говорите с ассистентом голосом, откуда удобно.

ГЛАВНОЕ ОТЛИЧИЕ: ДАННЫЕ ОСТАЮТСЯ У ВАС
• Нет аккаунта и облака KALI — мы ничего о вас не собираем.
• Голос и диалоги идут на ВАШ ПК по локальной сети, не нам.
• Диалоги, агенты и то, что ассистент о вас запомнил, хранятся на вашем компьютере.
• Никакой рекламы, трекинга и аналитики внутри приложения.

ЧТО УМЕЕТ
• Говорите с ассистентом голосом — он слышит вас и отвечает.
• Создавайте собственных голосовых агентов под свои задачи — без программирования.
• Дашборд: ваши агенты и их статус под рукой.
• Поделитесь созданным агентом с другом через обычное меню «Поделиться» вашего телефона — он установит точно такого же агента себе. Без чужих аккаунтов и привязок.

ДЛЯ КОГО
Для обычных людей, а не для разработчиков. Строитель, врач, таксист, офисный работник — если вы умеете говорить, вы умеете создать агента.

КАК ЭТО РАБОТАЕТ
1. Установите настольный KALI на свой ПК (см. сайт).
2. Откройте это приложение и укажите IP-адрес компьютера в той же сети.
3. Нажмите микрофон и говорите.

ЧЕСТНО О ТРЕБОВАНИЯХ
• Нужен компьютер с настольным KALI в той же Wi-Fi-сети — приложение само по себе не работает без него.
• Для локального голоса на ПК желателен современный GPU; есть и облачный голос, если вы подключите свой ключ.
• Подключайтесь в доверенной сети (например, домашней): локальный канал между телефоном и ПК пока не шифруется.

ПРИВАТНОСТЬ
Локальная обработка «на устройстве» — это основа KALI. Подробности — в политике конфиденциальности.

Микрофон используется только когда вы говорите с ассистентом. Доступ в сеть — чтобы соединиться с вашим ПК.
```
*(~1500 characters — well within the 4000 limit; room to expand once final feature set is locked.)*

---

## EN (secondary)

### App title (≤ 30 chars)

```
KALI — Voice AI Assistant
```
*(25 characters.)*

### Short description (≤ 80 chars)

```
Voice AI assistant. Build agents by voice. Your data stays on your own PC.
```
*(73 characters.)*

### Full description (≤ 4000 chars)

```
KALI is a voice AI assistant you control from your phone — while all the work runs on YOUR own computer.

This app is a companion to the KALI desktop. You run KALI on your PC, connect your phone to it over your home network, and talk to your assistant by voice from wherever you are.

THE DIFFERENCE: YOUR DATA STAYS WITH YOU
• No KALI account, no KALI cloud — we collect nothing about you.
• Your voice and conversations go to YOUR PC over the local network, not to us.
• Conversations, your agents, and anything the assistant remembers are stored on your computer.
• No ads, no tracking, no analytics inside the app.

WHAT IT DOES
• Talk to your assistant by voice — it hears you and replies.
• Build your own voice agents for your tasks — no coding required.
• Dashboard: your agents and their status at a glance.
• Share an agent you built with a friend using your phone's normal Share sheet — they install the exact same agent. No third-party accounts, no sign-ins.

WHO IT IS FOR
Made for everyday people, not developers. If you can talk, you can create an agent.

HOW IT WORKS
1. Install the KALI desktop app on your PC (see the website).
2. Open this app and enter your computer's IP address on the same network.
3. Tap the microphone and speak.

HONEST ABOUT REQUIREMENTS
• You need a computer running the KALI desktop on the same Wi-Fi network — this app does not work on its own without it.
• Local voice on the PC works best with a modern GPU; cloud voice is also available if you add your own key.
• Connect on a network you trust (e.g. your home Wi-Fi): the local channel between phone and PC is not yet encrypted.

PRIVACY
On-device, local-first handling is the core design of KALI. See our privacy policy for details.

The microphone is used only while you are talking to the assistant. Network access is used to connect to your PC.
```
*(~1450 characters.)*

---

## Graphics checklist (Play requires these before submission)

> Not produced here (write-only-under-docs constraint). Listed so nothing is missed.

| Asset | Spec | Status |
|---|---|---|
| **App icon** | 512×512 PNG, 32-bit | Source exists in app (`@mipmap/ic_launcher`); export the store 512px version. `<PRODUCE>` |
| **Feature graphic** | 1024×500 PNG/JPG | `<PRODUCE>` — required. |
| **Phone screenshots** | 2–8 images, min 320px, 16:9 or 9:16 | Candidates already in repo root (`mobile_dashboard.png`, `mobile_live_01/02/03.png`, `mobile_connected.png`) — confirm they reflect the shipped UI and are free of any JARVIS/Iron-Man-trademarked or movie-derived branding before upload. `<SELECT + VET>` |
| **(Optional) Promo video** | YouTube URL | `<OPTIONAL>` |
| **Tablet screenshots** | If you mark tablet support | `<OPTIONAL>` |

---

## Pre-submission cross-checks (do these before you hit "Send for review")

1. **Brand/IP risk in store assets.** The desktop persona uses the "JARVIS" wake word and an Iron-Man-derived voice reference (documented risk in project memory `project_brand_naming`, and the bundled `jarvis_ref_v2.wav`). **Do not** put "JARVIS", "Iron Man", "Tony Stark", Marvel marks, or movie audio/imagery in the Play **title, description, icon, screenshots, or feature graphic** — that invites a trademark/IP takedown and a possible Play rejection. Note: `mobile/lib/core/share_config.dart:24` currently lists `'Jarvis'` as a default share hashtag — that ships in user-generated captions, not the store listing, but flag it for the same reason. *(This is a listing-copy guardrail, not a code change — code is out of scope for this task.)*
2. **Functional dependency disclosure.** Because the app is non-functional without the desktop on the same LAN, the description states this plainly (above) to avoid "broken app" 1-star reviews and policy issues around misleading functionality.
3. **Data safety form** must match `privacy-policy.md`: declare microphone/audio as *processed, not collected by us / not shared*, no analytics, no ads. Be precise — Data Safety mismatches are a common rejection cause.
4. **Login/account:** there is none in this app — answer Play's "does your app have a login?" as **No**, and note reviewers cannot test voice without a paired desktop (provide review instructions, see below).

---

## Reviewer instructions (paste into "App access" / review notes)

```
This app is a LAN companion to the KALI desktop application. With no desktop
running on the same network, the app opens to a connection screen and cannot
demonstrate voice features (by design — it is a remote control, not a
standalone product). There is NO login/account.

To fully exercise it, a desktop KALI instance on the same network is required;
if the review needs that, contact <PUBLISHER_CONTACT_EMAIL> and we will provide
a test setup or a recorded walkthrough. Microphone permission is used only to
stream the user's speech to their own PC; no audio is sent to our servers.
```

---

### Verification notes (remove before publishing)

- `applicationId = ai.kali.mobile` — `mobile/android/app/build.gradle.kts:22`.
- "No ads / no analytics" — `mobile/pubspec.yaml` has no ad/analytics dependency.
- Native share sheet, no platform OAuth — `mobile/lib/presentation/share_to_reels_screen.dart:100`.
- P2P agent install via `kali://import` link — `mobile/lib/core/deep_link_service.dart`, manifest intent-filter `AndroidManifest.xml:35-40`.
- Local-only data, no KALI cloud account — `mobile/lib/core/config.dart:3` (server IP defaults to none), `kernel/database.py` (data persists per-install on the PC).
- LAN cleartext caveat — `AndroidManifest.xml:7`.
- Store URL placeholder acknowledged in code — `mobile/lib/core/share_config.dart:16-19`.
