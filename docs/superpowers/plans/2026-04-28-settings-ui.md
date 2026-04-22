# Settings UI — Plan Stub

> Status: STUB. Создан 2026-04-22. TIER 1 BLOCKER для non-tech использования.

**Goal:** UI-based configuration вместо редактирования `%APPDATA%\KALI\.env` руками. Non-tech user должен иметь возможность настроить API keys, провайдеров, agent integrations без текстового редактора.

## Depends on

- **holographic-design-tokens** — тех же токенов для settings panels
- **onboarding-flow** — частично пересекается (step 2 API key), но settings = full editable после

## In scope

### Settings panel structure
Сайдбар с группами:
- **LLM провайдеры** (OpenAI, Anthropic, Google, DeepSeek)
- **Голос** (F5 local / ElevenLabs cloud, voice_id override, speed)
- **Интеграции** (Google Calendar/Gmail OAuth, Home Assistant URL+token, Telegram bot)
- **Режим работы** (Wake word on/off, continuous mode, quiet hours)
- **Продвинутые** (config.yaml hot-reload, log level, models dir path)
- **О продукте** (version, update check, feedback button)

### Key management UX
Каждое поле key:
- Masked input (`sk-xxx...xxx` показано, можно show/hide)
- **"Проверить"** кнопка с real-time API test + response excerpt
- Иконка статуса (● активен / ● ошибка / ○ не настроен)
- Линк **"Где взять?"** → встроенный 30-сек видео в модалку
- "Удалить" с confirm

### OAuth flows
- Google: кнопка "Подключить Google" → OS browser → callback → done
- Home Assistant: URL + token input с auto-detect локального HA на LAN
- Telegram: "Создать бота" → steps wizard (@BotFather → copy token → paste)

### Configuration persistence
- Backend endpoints: `GET /settings`, `PUT /settings/{key}`, `POST /settings/test/{provider}`
- Changes apply immediately where possible (hot reload config_manager)
- Для некоторых (voice provider) — требует restart prompt
- History: "Последние изменения" (небольшой audit log последних 10 правок)

### Import/Export
- "Экспорт настроек" → JSON без keys (keys отдельно по consent)
- "Импорт настроек" — restore config, но keys требуют re-entry

## Out of scope

- **Cloud-sync настроек** между устройствами (после mobile + KALI Cloud)
- **Team/org settings** (Pro/Team tier — отдельно)
- **Per-agent config UI** — остаётся в Agent Details modal (Agent Store v2)

## Risks

- **Storing keys in plaintext** (.env) — для MVP ОК, но нужна `keytar`-like secure storage на later. Document в risks.
- **Test-call cost** — LLM test = ~$0.01 per call. Throttle + warn user about cost.
- **OAuth redirect loopback** — требует `http://localhost:8765/callback` или similar. Test on friend machines for firewall issues.

## Success criteria

- Non-tech user настраивает OpenAI + Google Calendar за ≤5 минут (timed)
- 0 editing of `.env` required после onboarding
- "Проверить" кнопка работает для всех 4 LLM providers
- Config changes apply без restart в 80%+ случаев

## Estimate

2-3 дня соло.

## Implementation sketch

Backend (мелкие изменения в `kernel/config.py` + new endpoints в `main.py`):
- `GET /settings` returns redacted config
- `PUT /settings/{key}` with validation per-key
- `POST /settings/test/openai` → real `client.chat.completions.create(...)` with 5 tokens max

Frontend (новый `ui/src/components/Settings/SettingsPanel.tsx`):
- Zustand store `stores/settings.ts`
- Per-section components (LLMSettings, VoiceSettings, etc)
- Shared `<SecretField>` component (mask + show/hide + test button)
