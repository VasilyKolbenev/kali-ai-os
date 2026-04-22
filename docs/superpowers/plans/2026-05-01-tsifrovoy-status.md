# Цифровой Статус (replaces Dashboard) — Plan Stub

> Status: STUB. Создан 2026-04-22. Replaces текущий примитивный Dashboard.

**Goal:** Превратить текущий "Dashboard с 7 пустыми карточками" в JARVIS-style daily surface — "Цифровой статус" с приветствием, приоритетами, пульсом, активными агентами и лентой событий.

## Naming

**"Цифровой статус"** (утверждено 2026-04-22).

Динамический подзаголовок по контексту:
- Утро: *"Доброе утро, сэр. 08:34. Все системы в норме."*
- День: *"Операционный режим · 14:12 · 9 агентов активны"*
- Вечер: *"Итоги дня. Приоритетов осталось: 2."*
- Ночь: *"Ночной режим. Будильник 07:00."*

## Depends on

- **holographic-design-tokens** — PulseOrb в hero, scan-line background, counter reveals
- **agent-store-v2** — shared `VoiceHero` компонент
- **onboarding-flow** — user должен попасть сюда сразу после onboarding step 5

## In scope

### Header area (hero)
```
┌─────────────────────────────────────────────┐
│  [PulseOrb]  Цифровой статус                 │
│              Доброе утро, Василий. 08:34.    │
│              Все системы в норме.            │
└─────────────────────────────────────────────┘
```
- LLM-generated greeting (persona + контекст)
- System health indicator (F5/ElevenLabs, агенты count, backend uptime)

### Voice hero (shared с Agent Store)
```
🎤  Скажите команду, сэр
    [Pulsing orb mic button]
```

### "Приоритеты сегодня" (LLM-picked top 3)
- Backend endpoint `/briefing/priorities` — LLM берёт (calendar + tasks + weather + reminders) и выбирает 3 самых важных
- Для каждого — actionable text с context:
  - *"10:00 Встреча с дизайнером — через 1.5 часа"*
  - *"3 задачи с дедлайном сегодня"*
  - *"11°C пасмурно — возьмите куртку"*
- Клик → открыть детали в relevant agent

### Пульс (vitals row)
Тонкая строка с live-metrics, не карточки:
```
сон 7.2ч  ·  вода 1.2/2.0л  ·  энергия 1800 ккал  ·  шаги 4200
```
- Только те что есть (отсутствующие скрыты, не показывают "—")
- Data sources: life-dashboard agent, health integrations (будущее Garmin/Apple)
- Прогрессы с glow indicator при приближении к цели

### Активные агенты (живой список)
- 9 most-recently-active с last action
- Status dot (● running / ● error / ○ offline)
- Hover → quick actions preview
- Link "ещё N →" если больше

### Лента событий
- Timeline последних 10-20 событий из event bus
- Формат: `09:45 tracker-water: утренняя отметка 500мл`
- Group by agent opcionально
- Scroll reveals older

### "Прочитать вслух" action
- Кнопка/голос-триггер "сводка" → JARVIS озвучивает приоритеты + пульс
- TTS тот же что везде (F5/ElevenLabs)

## Out of scope

- **Custom widgets user adds** — pinning/unpinning (v2 of v2)
- **Multi-profile dashboard** (несколько user контекстов)
- **Calendar full view** — остаётся в calendar agent; здесь только top events
- **Historical charts** (vitals trends — отдельный View "Analytics")

## Risks

- **LLM priorities latency** — вызов каждые N минут ест tokens. Mitigation: cache 10 минут + regenerate on explicit refresh/voice.
- **Too much data at once** — если все секции полные, overwhelming. Collapse sections с "hide if empty".
- **Stale data** — если агент offline, его vitals показывают old. Add "(3ч назад)" badges.
- **Greeting loop** — LLM generates same greeting if context same. Add some randomness + recent-history memory.

## Success criteria

- User открывает Цифровой статус → за 10 секунд знает: что сегодня важно, что делают агенты, как он себя чувствует
- "Прочитать вслух" triggered ≥ 3 раз/день у active users (signal: useful)
- Приоритеты accuracy — LLM picks top 3 с ≥80% user-agreement (опрос)
- D30 daily return rate для users открывавших Цифровой статус ≥ 70%

## Estimate

3-5 дней соло.

## Implementation sketch

Backend:
- `/briefing/today` — aggregator собирает calendar + tasks + weather + vitals
- `/briefing/priorities` — LLM picks top 3 (streaming preferably)
- `/briefing/activity?limit=20` — event bus feed
- `/vitals/today` — collects from life-dashboard + integrations

Frontend:
- `ui/src/components/Status/CifrovoyStatus.tsx` (replaces Dashboard.tsx)
- `GreetingHeader`, `VoiceHero` (shared), `PrioritiesShelf`, `VitalsRow`, `ActiveAgentsList`, `ActivityFeed`
- Auto-refresh every 60s (configurable)
