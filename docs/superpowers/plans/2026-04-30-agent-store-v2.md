# Agent Store v2 — Plan Stub

> Status: STUB. Создан 2026-04-22. Главный discovery surface — из "вкладки со списком" в "App Store + TikTok".

**Goal:** Переработать Agent Store из плоского списка с generic CTA-кнопкой в **центральный hub** продукта: voice-first create entry + featured/trending + категории + installed shelf + details modal + install feedback. В соответствии с vision "voice-first creator for normies + UGC distribution".

## Depends on

- **holographic-design-tokens** — все новые компоненты должны использовать токены сразу
- **voice-builder-pilot** — voice-create entry из Store uses builder flow
- **NeuralDeep integration** (уже сделана) — для русской секции и trending

## In scope

### Hero section — voice create CTA
```
🎤  Скажи что нужно — сделаем агента
    [Большая mic-кнопка — pulsing orb]
```
- Клик → voice builder flow (из pilot)
- Optional chips с примерами внизу для text input альтернативы

### Trending / Featured carousel
- Top 5 агентов с thumbnail + preview-видео (если есть) + installs count
- Sources: NeuralDeep `featured=true` + `trending24h` + user-installed signals
- Auto-rotate, pause on hover

### "Твои агенты" shelf (не отдельная вкладка, на том же экране)
- Живой список установленных со статусом (running / stopped / error)
- Last action per agent ("трекер воды — 14:30: 200мл")
- Quick actions: запустить / остановить / настроить / удалить
- **"Переделать голосом"** кнопка — prefills voice builder с existing agent spec как basis (remix)

### Categories shelves
Явные "полки":
- 💼 **Работа** (calendar, email, github, tasks)
- 🏥 **Здоровье** (water, mood-diary, meds, sleep)
- 💰 **Деньги** (expenses, crypto, subscriptions, savings)
- 🏠 **Быт** (cooking-timer, shopping, plants)
- 🇷🇺 **Российские** (NeuralDeep: Яндекс, 1С, Битрикс, GigaChat)
- 🤖 **От сообщества** (community-published)

Lazy-load per shelf, горизонтальный scroll в каждой.

### Agent card redesign
Новая `<AgentCard>`:
- Thumbnail/icon (не generic lightning bolt — real icon per agent)
- Название + автор (`@vasily` → clickable profile)
- 1-line описание на простом языке (без tech-speak)
- **Human metric:** "Установили: N" когда N>0, скрыто когда 0
- Badges: ⭐ Featured / ✓ Verified / 🇷🇺 RU / 🆕 New / 🔥 Trending
- Hover → subtle glow + scale (от design tokens)
- Click → Detail modal

### Agent Detail Modal
- Full description
- **3-5 примеров команд** ("Скажи: 'напомни пить воду каждые 2 часа'")
- Видео-demo если есть
- Требования (API keys, OAuth, permissions)
- Installs / ratings (если есть)
- Tools list (transparent — что агент умеет)
- Buttons:
  - **"Попробовать"** (ephemeral invoke без установки — опция, если возможно)
  - **"Установить"** — progress bar + success toast с примером команды
- Share button (hook для share-to-reels позже)

### Install feedback
- Progress modal: "Загружаю... Проверяю... Готово!"
- Success toast: **"Агент X установлен. Попробуй: 'команда-пример'"** с кнопкой "К чату"
- Если требует API key/OAuth — wizard prompt сразу после install

### Search + filters
- Full-text поиск по name + description + tags
- Фильтры: Категория / Источник (Local/NeuralDeep/GitHub) / Статус (Installed/Not) / Language (RU/EN)
- Voice-triggered: "покажи агенты для Х" → Store открывается pre-filtered

## Out of scope

- **Ratings / Reviews UI** (появится после Profile / UGC plans)
- **Comments / Discussions** (Community tier)
- **Paid agents** (after Pro tier monetization infra)
- **Agent marketplace для продажи third-party** (future)
- **Real-time collaborative agents** (team tier)

## Risks

- **Empty catalog на старте** — если установлено 0 агентов и каталог cold, Store выглядит пусто. Mitigation: hero + featured всегда показывают что-то; categories с placeholder'ами "Скоро здесь будут агенты".
- **NeuralDeep aggregator downtime** — если их API недоступен, RU section empty. Graceful fallback + retry.
- **Icon/thumbnail ownership** — не у всех агентов есть thumbnail. Auto-generate colored icon с первыми буквами name?
- **Install collisions** — user ставит два агента с одинаковым name из разных sources. Need disambiguation in Detail modal.

## Success criteria

- Non-tech user открывает Store → за 30 секунд понимает что он может делать
- Install-to-first-use time ≤ 1 мин (поставил → увидел пример → сказал → получил ответ)
- CTR на "Попробовать голосом" hero ≥ 20% sessions
- Average agents installed per user ≥ 5 (baseline currently: 1-2)

## Estimate

7-10 дней соло. Самый большой план после voice-builder-pilot.

## Split by chunks

1. **Chunk 1:** Hero + VoiceCreateCTA integration with voice-builder-pilot (~1 день)
2. **Chunk 2:** InstalledAgentsShelf + RemixButton (~1.5 дня)
3. **Chunk 3:** CategoryShelves + lazy loading (~2 дня)
4. **Chunk 4:** AgentCard redesign + DetailModal (~2.5 дня)
5. **Chunk 5:** Install flow + toast + voice search entry (~1.5 дня)
6. **Chunk 6:** Polish + a11y + tests (~1.5 дня)

Каждый chunk — working software, можно ship incrementally.
