# Feedback Channel — Plan Stub

> Status: STUB. Создан 2026-04-22. TIER 1 BLOCKER для observability (solo dev без feedback loop слеп).

**Goal:** 1-клик "Отправить фидбек" с авто-вложением лога + опциональный анонимный crash reporting. Без этого каждый bug = много ручной переписки, половина репортов теряется.

## Depends on

- **holographic-design-tokens** — стиль feedback modal
- Nothing blocking — можно делать любым спринтом

## In scope

### In-app feedback button
- Menu → "Отправить фидбек" (или hotkey Ctrl+Shift+F)
- Modal с полями:
  - Тип: баг / фича / вопрос / благодарность
  - Описание (multiline, без limit)
  - **Checkbox "Приложить последние 200 строк лога" (default on)**
  - Checkbox "Приложить скриншот текущего экрана" (default on)
  - Checkbox "Анонимно" (default off — без имени/email attached)
- Сабмит → один из каналов (config):
  - GitHub Issues API (default — создаёт issue в private/public repo)
  - Telegram bot webhook (для private feedback)
  - Email (smtp настройка)

### Auto-attached diagnostics
- Last 200 lines from `%APPDATA%\KALI\logs\kali-backend.log`
- App version, OS version, Python version, GPU info
- Active voice provider + loaded status
- List of installed agents + their status
- **Никогда не включается:** API keys, user messages, file contents

### Opt-in telemetry
- Settings → "Помогать улучшать KALI" (off by default)
- Включает:
  - **Crash reporting**: uncaught exceptions sent anonymously (sentry-like)
  - **Usage stats**: какие агенты popular, какие фичи используются, durations, error rates
  - **Voice metrics**: TTS latency, STT accuracy (no audio stored)
- НЕ включает: тексты, голосовые записи, content of any kind

### Crash reporter
- Exception hook в backend main
- Captures stack + context (NO user data)
- Queued to disk if offline, uploaded on next launch
- Dedup by fingerprint

## Out of scope

- **Full Sentry integration** (self-hosted или cloud) — отдельный план если нужен
- **User interviews pipeline** — не automate contact
- **Public status page** с статистикой uptime и usage
- **Feedback replies в приложении** — user получает ответ через GitHub/Telegram/email

## Risks

- **Privacy** — abs нельзя отправлять voice recordings, user messages, или file content. Даже "анонимный" crash report должен redact paths (`C:\Users\Vasily\Documents\secret.txt` → `<REDACTED>`).
- **Log PII** — backend log может содержать user queries. Sanitize перед attach или ask user consent.
- **Rate-limiting** — если много users шлют фидбек → GitHub API exhausted. Queue + batch.
- **Trust** — если явно не показать что отправляется, users не включат telemetry. Show preview "Вот что будет отправлено" перед submit.

## Success criteria

- First bug report from friend-tester приходит авто-attached со всем нужным контекстом — не надо писать "пришли лог"
- Среднее время ответа на bug ≤24ч (instead of ≥3 days currently)
- Crash reports показывают 5+ unique stack traces в первый месяц distribute — все исправлены до Day 14 следующего

## Estimate

2-3 дня соло.

## Implementation sketch

Backend (new `kernel/feedback.py`):
- `POST /feedback` принимает body + attachments, forward в configured channel
- Sanitizer для путей, PII, keys
- `POST /crash-report` (called by exception hook if opted in)

Frontend (`ui/src/components/Feedback/FeedbackModal.tsx`):
- Modal триггерится menu/hotkey
- Preview panel показывает что будет отправлено
- После submit — "Спасибо. Ссылка: https://github.com/.../issues/42"
