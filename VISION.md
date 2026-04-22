# KALI — Voice-First AI Agent Creator для обычных людей

> Скажи идею — получи работающего AI-агента за 60 секунд. Запиши reel → покажи друзьям → они ставят KALI и делают своих. **Прорыв, а не решение сбоку индустрии.**

---

## Mission (обновлено 2026-04-22)

**KALI — это когда офисный работник, строитель или врач говорит "хочу агента, который считает кирпичи по фото и напоминает про смену" — и через минуту он у него в кармане работает.** Без кодинга, без разработчиков, без настроек.

**Target persona = НЕ разработчики.** Это строитель 35 лет, медсестра, офисный менеджер — люди далёкие от IT, которые берут жизнь под контроль через голосовые AI-агенты, делятся результатом в TikTok/Reels и растят сообщество.

**Distribution thesis = UGC viral loop:**
```
создал агента голосом → записал reel → друзья видят → ставят KALI → создают своих → повтор
```
Цель: **K-factor ≥ 1** (каждый пользователь приводит ≥1 нового за 30 дней).

**Platform roadmap:**
- **Desktop (now)** — "Studio" для создания агентов (pro-users, early adopters)
- **Mobile (next)** — "Consumer" для запуска+простого создания агентов на ходу
- **Hardware (future)** — KALI Device + Starlink для всегда-на-связи работы

**Техническая база — Agent Skills native (Anthropic standard):** мы совместимы с открытой экосистемой, но наш **unique angle = voice-first creation flow для нормисов**, а не "ещё один клиент для разработчиков".

**Что KALI НЕ является (anti-positioning):**
- ❌ Cursor / Copilot для голоса — это для разработчиков
- ❌ Raycast / Alfred с AI — это для power-users
- ❌ Siri / Alexa — это voice assistant, а не agent creator
- ✅ **Мы — первая платформа где non-tech человек создаёт своего AI-агента голосом и делится им как TikTok-видео.**

## Core Principles

1. **Voice-first** — всё управляется голосом, UI вторичен
2. **Production-grade, always** — не прототип. Каждый релиз — rock-solid. Миллионы пользователей — требования dayone: скорость, надёжность, отсутствие багов
3. **Standard-compliant** — нативная поддержка Agent Skills spec ([agentskills.io](https://agentskills.io))
4. **No-code by default** — любой человек без опыта может создать скилл голосом
5. **Local-first, cloud-enhanced** — работает офлайн, облако усиливает
6. **Ecosystem interop** — наши скиллы работают везде, чужие работают у нас
7. **Safe by design** — песочница, permissions, AST code review

## Business Model

**Phase 1 (now → Q3 2026):** Software subscription
- **Free tier** — KALI Core: local voice, 5 built-in agents, basic skills
- **Pro $9.99/мес** — ElevenLabs JARVIS cloud voice, priority LLM routing, cloud skills sync
- **Team $29/мес** — shared workspaces, admin console, on-prem option

**Phase 2 (Q4 2026 → 2027):** Hardware + subscription
- **KALI Device** (aka "CLIK") — custom hardware with built-in mic array, speaker, offline AI chip
- **$399 one-time + $9.99/мес** — железка unlocks full features, подписка покрывает cloud LLM
- Target: satellite connectivity (Starlink integration), always-connected

**Technical requirements for monetization readiness:**
- [ ] Auth layer (user accounts, OAuth via Google/GitHub/Apple)
- [ ] License server (JWT tokens, feature flags per tier)
- [ ] Billing integration (Stripe for Web, In-App Purchase for mobile)
- [ ] Telemetry (opt-in) — usage metrics для product decisions
- [ ] Team admin console (enterprise feature)

Эти фичи — **архитектурно** закладываем сейчас (feature flags, auth middleware), **реализация** после validation MVP.

## Production Quality Standards

KALI — **не dev-прототип, а продукт для миллионов**. Каждая строка кода подчиняется:

**Performance:**
- App startup ≤ 2s (cold), ≤ 500ms (warm)
- Voice response latency ≤ 1.5s (end-to-end: wake word → ответ с TTS)
- Memory footprint ≤ 500 MB idle, ≤ 2 GB under load
- Никаких fork-bomb, memory leaks, UI freeze

**Reliability:**
- Zero crashes on main workflow (voice command → response)
- Graceful fallbacks: GPU fail → cloud, network fail → offline mode
- Auto-recovery: backend crash → auto-restart с сохранением state
- Comprehensive logging + telemetry (opt-in)

**Distribution:**
- Code-signed installers (Windows SmartScreen, macOS notarization)
- Auto-update mechanism (Sparkle/Squirrel-style)
- Installer ≤ 200 MB для Lite, ≤ 4 GB для Premium
- Works on 5-year-old hardware (4GB RAM, CPU-only fallback)

**UX:**
- Every action has loading state + error handling
- No "it works on dev machine" — тест на clean Windows VM перед каждым релизом
- Localization ready (RU/EN, growth to 10+ languages)
- Accessibility compliant (keyboard navigation, screen reader support)

---

---

## User Experience — "AI в кармане"

### Голосовая активация

KALI всегда слушает wake word **"Jarvis"** (или кастомное имя). Активация мгновенная — нет кнопок, нет экранов, нет ожидания.

**Режимы активации:**
- **Wake Word** — "Jarvis, ..." → система слушает и выполняет
- **Push-to-Talk** — Ctrl+Space (десктоп) или кнопка на устройстве
- **Continuous** — hands-free, система всегда в диалоге
- **Tap to Talk** — тап по экрану на мобильном/планшете

### Повседневные сценарии

**Утро:**
```
Пользователь: "Jarvis, доброе утро"
Jarvis: "Доброе утро, сэр. Сегодня вторник, 15 апреля. 
         На улице 12 градусов, к обеду потеплеет до 18.
         У вас 3 встречи: стендап в 10, обед с Максом в 13, 
         созвон с клиентом в 16. 
         Вчера вы выпили 1.5 литра воды из двух — напоминать сегодня чаще?
         Бюджет на еду: осталось 4200 из 8000 на неделю."
```

**В течение дня:**
```
"Jarvis, добавь задачу — позвонить в банк до пятницы"
"Jarvis, сколько я потратил за сегодня?"
"Jarvis, включи свет в гостиной на 50%"
"Jarvis, что нового по моим акциям?"
"Jarvis, напомни через 30 минут проверить духовку"
```

**Идеи и креатив:**
```
"Jarvis, у меня идея — хочу отслеживать свой прогресс по чтению книг"
→ Jarvis создаёт Skill-трекер через Voice Wizard

"Jarvis, мне нужно чтобы ты проверял курс биткоина каждый час 
 и писал мне в телеграм когда будет ниже 60 тысяч долларов"
→ Jarvis создаёт Agent через Voice Wizard с permissions: network + telegram
```

**Помощь в решениях:**
```
"Jarvis, стоит ли мне сейчас лететь в Стамбул? Что с ценами?"
→ Агент Aviasales/travel ищет варианты, анализирует тренды

"Jarvis, как оптимизировать мои расходы на еду?"
→ Агент finance анализирует траты, предлагает рекомендации
```

**Социальные:**
```
"Jarvis, отправь Маше в телеграм что буду через 20 минут"
"Jarvis, напиши черновик письма клиенту об отмене встречи"
"Jarvis, кто мне писал за последний час?"
```

### Proactive Intelligence — Jarvis сам предлагает

KALI не только отвечает — система учится и предлагает:

- **"Сэр, вы обычно пьёте кофе в это время. Сегодня уже третья чашка — может, переключиться на воду?"**
- **"Заметил, что вы тратите на такси больше обычного. Хотите чтобы я мониторил когда каршеринг дешевле?"**
- **"Ваш рейс через 4 часа. Пробки средние — рекомендую выехать в 14:30."**
- **"У вас есть 30 свободных минут до встречи. Хотите сделать задачу «позвонить в банк» из списка?"**

### Персонализация

KALI запоминает предпочтения и адаптируется:

- **Стиль общения** — формальный/дружеский, краткий/подробный
- **Голос** — JARVIS по умолчанию, кастомные голоса через клонирование (F5-TTS / ElevenLabs)
- **Расписание** — знает когда вы просыпаетесь, работаете, отдыхаете
- **Привычки** — отслеживает паттерны и предлагает улучшения
- **Контекст** — помнит предыдущие разговоры и решения

### Multi-Device (v3+)

- **Desktop** — основная рабочая станция (Tauri)
- **Mobile** — companion app (React Native) 
- **Smart Speaker** — Raspberry Pi + микрофон
- **Wearable** — smartwatch notifications
- Все устройства синхронизируются через облако — один ассистент везде

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    KALI Desktop Shell                        │
│         Tauri 2.x (Rust) + React 19 + Three.js              │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌──────────────┐  │
│  │ 3D Avatar│  │Dashboard │  │ Chat   │  │ Agent Store  │  │
│  │ (WebGL)  │  │(Widgets) │  │(Voice) │  │ (Marketplace)│  │
│  └──────────┘  └──────────┘  └────────┘  └──────────────┘  │
│                     WebSocket / Tauri IPC                    │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────┐
│                    KALI Kernel (Python)                       │
│                    FastAPI + Async                            │
│                                                              │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐  │
│  │Event Bus │ │Config Mgr │ │Plugin Reg│ │  Scheduler   │  │
│  │(pub/sub) │ │(YAML)     │ │(manifest)│ │  (cron)      │  │
│  └──────────┘ └───────────┘ └──────────┘ └──────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Agent Runtime                            │   │
│  │  ┌────────────┐ ┌────────────┐ ┌──────────────────┐  │   │
│  │  │ Subprocess │ │ Permission │ │ Network Proxy    │  │   │
│  │  │ Manager    │ │ Enforcer   │ │ (domain whitelist)│  │   │
│  │  └────────────┘ └────────────┘ └──────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           AgentBuilder (LLM-powered)                  │   │
│  │  Voice Wizard → Intent → Generate → Safety → Deploy   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Voice Pipeline                           │   │
│  │  Mic → VAD → Wake Word → STT → LLM Router → TTS          │   │
│  │       (Silero VAD)  (Whisper) (Claude) (F5-TTS/ElevenLabs) │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LLM Router                               │   │
│  │  Intent → Agent Selection → Tool Calling → Response   │   │
│  │  (Claude API / Ollama local fallback)                 │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
         │                              │
         │ JSON-RPC (stdio)             │ REST API
         ▼                              ▼
┌─────────────────┐            ┌─────────────────┐
│  Native Agents  │            │  Cloud Catalog  │
│  (subprocesses) │            │  (Supabase)     │
└─────────────────┘            └─────────────────┘
```

---

## Architecture: Agent Skills Native

KALI принял **Agent Skills спецификацию** ([agentskills.io](https://agentskills.io)) как родной формат. Каждая "способность" — это **SKILL.md** файл в папке (YAML frontmatter + Markdown инструкции).

### SKILL.md — единый формат

```markdown
---
name: water-tracker
description: Tracks daily water intake with reminders every 2 hours.
  Use when user mentions hydration, water, drinking habits.
license: MIT
metadata:
  author: kali-team
  version: "1.0"
allowed-tools: Read Write
---

# Water Tracker

Instructions for the agent...

## Script
Run `scripts/log-intake.py` to record an entry.
```

### Структура папки скилла

```
water-tracker/
├── SKILL.md          ← обязательный: metadata + инструкции
├── scripts/          ← опциональный: Python/Bash код
│   └── log-intake.py
├── references/       ← опциональный: детальные документы
└── assets/           ← опциональный: шаблоны/данные
```

### Двухуровневая модель сложности

| Тип | Когда | Пример |
|---|---|---|
| **Instruction-only skill** | Не нужен код, только инструкции для LLM | "Напоминай пить воду каждые 2 часа" |
| **Skill with scripts** | Нужны API-вызовы, парсинг, интеграции | "Отслеживай курс биткоина и уведомляй" |

Agent Skills spec поддерживает оба варианта — один формат для всех случаев.

### Voice Wizard — поиск или создание

Jarvis сначала **ищет готовый скилл** в каталоге Agent Skills экосистемы (1100+ скиллов), потом — **создаёт новый** если не найден:

```
"Напоминай пить воду каждые 2 часа"     → Ищем existing skill → found "water-reminder" → install
"Интегрируй Home Assistant"             → Ищем → found "home-assistant-bridge" → install
"Мониторь цену биткоина на Binance"     → Ищем → found "crypto-monitor" → configure
"Сделай что-то очень специфичное"        → Не найдено → LLM generates new SKILL.md → publish
```

### Почему Agent Skills вместо своего формата

| | Свой формат (manifest.yaml) | Agent Skills (SKILL.md) |
|---|---|---|
| Контент на старте | 0 скиллов | **1100+ готовых** |
| Экосистема | Только KALI | **30+ инструментов** (Claude, Cursor, VS Code...) |
| Portability | Lock-in | Пишем 1 раз — работает везде |
| Standards | Никаких | Открытый стандарт Anthropic |
| Discoverability | Свой каталог | GitHub CLI `gh skill search` + наш UI |

---

## Sandbox & Permission Model

Вдохновлено NVIDIA NemoClaw — трёхслойная изоляция адаптированная для десктопа.

### Три слоя защиты

| Слой | Механизм | Что защищает |
|------|----------|-------------|
| **Filesystem** | Subprocess + restricted paths | Агент видит только `data/agents/{name}/` |
| **Network** | Proxy через kernel | HTTP-запросы только к разрешённым доменам |
| **Process** | Code scanner + subprocess isolation | Запрет опасных паттернов (`eval`, `exec`, `os.system`) |

### Permission Model (как на смартфоне)

```yaml
permissions:
  - storage                    # своя папка data/agents/{name}/
  - network:                   # HTTP доступ
      domains: ["api.example.com"]
  - event_bus:                 # подписка на события ядра
      topics: ["schedule.hourly"]
  - agents:                    # вызов других агентов
      allow: ["telegram", "email"]
  - notifications              # push-уведомления пользователю
```

### Approval Flow (голосовой)

1. AgentBuilder генерирует код + manifest с permissions
2. Kernel анализирует запрошенные permissions
3. Jarvis озвучивает: "Агент запрашивает доступ к сети и телеграм. Разрешить?"
4. Пользователь подтверждает голосом
5. Permissions кэшируются — повторно не спрашивает

### Safety Gate (перед запуском)

- **Static analysis** — блокировка опасных паттернов
- **LLM review** — Claude проверяет сгенерированный код
- **Runtime enforcement** — kernel-прокси для network/filesystem

---

## Cloud Catalog & Marketplace

### Архитектура

Backend на Supabase (PostgreSQL + Auth + Storage + Realtime).

**Сущности каталога:**
- **Packages** — Skills и Agents для установки
- **Authors** — профили создателей
- **Reviews** — рейтинги и отзывы
- **Categories** — здоровье, финансы, продуктивность, умный дом, разработка...

### Формат пакета `.kali-agent`

```
water-tracker.kali-agent (zip)
├── manifest.yaml        # метаданные + permissions
├── agent.py             # код (Agents) или отсутствует (Skills)
├── skill.yaml           # конфигурация шаблона (Skills)
├── icon.png             # иконка
├── README.md            # описание
└── signatures/
    └── author.sig       # подпись автора
```

### Уровни доверия

| Уровень | Бейдж | Как получить |
|---------|-------|-------------|
| **Official** | Встроенные агенты KALI | Команда KALI |
| **Verified** | Проверены командой | Code review + тестирование |
| **Community** | Авто-скан пройден | Любой пользователь публикует |

### Голосовые команды каталога

```
"Jarvis, найди агента для учёта расходов"
"Jarvis, опубликуй мой трекер воды"
"Jarvis, покажи популярных агентов за неделю"
"Jarvis, обнови все мои агенты"
"Jarvis, удали агента Budget Pro"
```

---

## AgentBuilder — LLM-Powered Voice Wizard

### Процесс создания

```
┌────────────────┐     ┌──────────────────┐     ┌───────────────┐
│  User Voice    │ ──→ │  Intent Analyzer  │ ──→ │ Skill or Agent│
│  "создай..."   │     │  (LLM decides)    │     │  decision     │
└────────────────┘     └──────────────────┘     └───────┬───────┘
                                                         │
                        ┌────────────────────────────────┤
                        ▼                                ▼
               ┌────────────────┐              ┌─────────────────┐
               │ Skill Builder  │              │ Agent Builder   │
               │ (YAML config)  │              │ (LLM codegen)   │
               └───────┬────────┘              └────────┬────────┘
                       │                                │
                       │                    ┌───────────┴──────────┐
                       │                    │ Safety Gate           │
                       │                    │ (static + LLM review)│
                       │                    └───────────┬──────────┘
                       │                                │
                       ▼                                ▼
               ┌─────────────────────────────────────────────────┐
               │        Permission Approval (voice)              │
               └─────────────────────┬───────────────────────────┘
                                     │
                                     ▼
               ┌─────────────────────────────────────────────────┐
               │            Deploy & Run                         │
               └─────────────────────────────────────────────────┘
```

### Voice Wizard Dialog

AgentBuilder использует guided wizard — задаёт 2-4 уточняющих вопроса голосом:

1. **Что делать?** — суть функции
2. **Как часто?** — расписание/триггеры
3. **Куда отправлять?** — уведомления (голос, телеграм, дашборд)
4. **Нужен доступ?** — API, другие агенты (только для Agents)

### LLM Code Generation (для Agents)

Claude генерирует полный `agent.py` наследующий `BaseAgent`:
- `manifest.yaml` с tools и permissions
- Код с type hints и error handling
- Тесты для валидации

---

## Voice Pipeline

### JARVIS Voice (Production, 2026-04-20)

**Two-tier TTS strategy:**

| Provider | Когда используется | Latency (typical) |
|---|---|---|
| **F5-TTS Russian v4_winter** (local GPU, RTX 5070+) | NVIDIA CUDA доступна | ~800ms |
| **ElevenLabs** (cloud, voice clone `LuMAgLODaXoM7gaV55sV`) | CPU-only / нет GPU / fallback | ~400ms (network) |

Выбор провайдера — автоматический через [kernel/voice/tts_router.py](kernel/voice/tts_router.py).
Короткие фразы (приветствия, "ок", "готово") — из pre-recorded JARVIS Sound Pack.

### Full Voice Loop

```
Mic → Silero VAD → Wake Word ("Jarvis")
    → faster-whisper STT (~200ms)
    → LLM Router (Claude / Ollama)
    → Agent Dispatch → Response
    → F5-TTS or ElevenLabs (~500ms)
    → Speaker
```

**Режимы:** Wake Word | Push-to-Talk | Continuous

---

## Built-in Agents (v1)

| Agent | Tools | Status | Description |
|-------|-------|--------|-------------|
| **system** | 3 | Production | Время, системная информация, таймеры |
| **tasks** | 5 | Production | Задачи: добавить, список, завершить, удалить |
| **calendar** | 3 | Production | Google Calendar + local fallback |
| **life-dashboard** | 4 | Production | Сон, расходы, калории, дневная сводка |
| **weather** | 2 | Production | Погода и прогноз (Open-Meteo, бесплатно) |
| **email** | 3 | Production | Gmail: inbox, send, search |
| **telegram** | 3 | Production | Сообщения и уведомления через бота |
| **smart-home** | 3 | Stub → v2 | Home Assistant интеграция |
| **coding** | 3 | Stub → v2 | Claude Code интеграция |

## Planned Agents (v2+)

| Agent | Category | Description |
|-------|----------|-------------|
| **fitness** | Здоровье | Garmin/Apple Health, тренировки, шаги |
| **finance** | Финансы | Банковские API, бюджет, инвестиции |
| **notes** | Продуктивность | Notion/Obsidian интеграция |
| **music** | Медиа | Spotify/Яндекс.Музыка управление |
| **transport** | Транспорт | Навигация, пробки, такси |
| **shopping** | Покупки | Списки, сравнение цен, заказы |
| **news** | Информация | Персонализированные новости и дайджесты |
| **social** | Коммуникации | Telegram, WhatsApp, VK интеграции |

---

## Tech Stack

### Backend (Kernel)
- **Python 3.12+** — ядро
- **FastAPI** — HTTP/WebSocket API
- **SQLite (aiosqlite)** — локальная БД
- **Pydantic** — модели данных

### Frontend (Shell)
- **Tauri 2.x** — desktop wrapper (Rust)
- **React 19** — UI framework
- **TypeScript** — типизация
- **Three.js / React-Three-Fiber** — 3D avatar
- **Zustand** — state management
- **Tailwind CSS** — стили

### Voice
- **F5-TTS Russian v4_winter** — синтез речи с voice clone (GPU via torch+cu128)
- **ElevenLabs** — cloud TTS fallback (voice clone `LuMAgLODaXoM7gaV55sV`)
- **faster-whisper** — распознавание речи
- **Silero VAD** — детекция голоса (voice activity detection)
- **OpenWakeWord** — wake word detection

### Cloud
- **Supabase** — маркетплейс backend (PostgreSQL + Auth + Storage)
- **Claude API** — LLM (intent routing, agent generation, code review)
- **Ollama** — local LLM fallback

### Agent Protocol
- **JSON-RPC 2.0** — native subprocess communication
- **HTTP REST** — external agent services
- **MCP** — ready for Model Context Protocol

---

## Implementation Roadmap

### Phase 1: Voice Foundation ✅ DONE
- [x] F5-TTS Russian voice clone (local GPU)
- [x] ElevenLabs cloud fallback (voice clone from JARVIS Sound Pack)
- [x] TTS router with auto-provider selection (CUDA → F5, else ElevenLabs)
- [x] faster-whisper STT + Silero VAD + OpenWakeWord
- [x] Pre-recorded clips for common phrases (no TTS round-trip)
- [x] ~~Legacy Silero+RVC+DirectML pipeline~~ (removed 2026-04-22)

### Phase 2: Core Kernel ✅ DONE
- [x] FastAPI async server
- [x] Event Bus (pub/sub with wildcards)
- [x] Config Manager (YAML hot-reload)
- [x] Plugin Registry (manifest discovery)
- [x] SQLite persistence
- [x] Scheduler (cron-like events)
- [x] WebSocket for real-time UI

### Phase 3: Agent Runtime ✅ DONE
- [x] Subprocess manager (JSON-RPC)
- [x] Protocol layer (native + HTTP)
- [x] Tool dispatcher
- [x] Agent lifecycle (load/dispatch/health/shutdown)
- [x] 9 built-in agents

### Phase 4: UI Shell ✅ DONE
- [x] React 19 + TypeScript frontend
- [x] Three.js animated blob avatar
- [x] Dashboard with widgets (real data: weather, tasks, calendar, sleep, spending)
- [x] Agent panel (start/stop agents)
- [x] Voice visualizer (Web Audio API FFT)
- [x] WebSocket real-time updates
- [x] Agent Store UI (browse, search, installed badges)
- [x] Builder UI (classify intent + create skill from text)
- [x] Settings page (4 LLM providers, language selector, API keys)
- [x] Tauri 2 desktop packaging (13 MB exe)
- [x] NSIS installer (KALI-Setup-0.1.0.exe, ~300 MB)
- [x] System tray + Ctrl+Space global hotkey
- [x] Russian labels throughout UI

### Phase 5: AI OS Layer ✅ DONE
- [x] AgentBuilder (LLM code generation — multi-provider: OpenAI/Anthropic/Google/DeepSeek)
- [x] Code Safety Gate (true AST analysis, blocks dangerous imports at install time)
- [x] Intent Classifier (LLM mode with regex fallback — 2026-04 upgrade)
- [x] Skill templates (tracker, monitor, notifier, reminder, logger)
- [x] Skill template declarations preserved as reference (superseded by SKILL.md in Phase 6)
- [x] Permission Enforcer wired at dispatch (Phase 6)
- [x] Rate Limiter wired at dispatch (120/min sliding window, Phase 6)
- [x] SQLite audit log for all dispatches (Phase 6)
- [x] SandboxBackend Protocol — pluggable for future Docker/CubeVM/E2B (Phase 6)
- [x] Deployer with rollback on failure (Phase 5 migration)
- [~] Voice Wizard (session tracking exists, multi-turn flow incomplete)
- [ ] Network Proxy runtime patching (JSON-RPC handler ready, not plugged into scripts)
- [ ] Agent-to-agent communication (v2.5)

### Phase 6: Agent Skills Native Support ✅ DONE
**2026-04: Полный переход на Agent Skills spec** ([agentskills.io](https://agentskills.io)) — 
открытый стандарт Anthropic, совместимый с 30+ tools (Claude Code, Cursor, Copilot…).

**Adoption layer (6.1):**
- [x] **SKILL.md loader** — parser frontmatter + Markdown (kernel/skills/loader.py)
- [x] **Converter** — existing agents/*/manifest.yaml → SKILL.md (15 agents migrated)
- [x] **Validator** — spec-compliant (name/description/license/compatibility/metadata/allowed-tools)
- [x] **Dual plugin registry** — supports SKILL.md AND legacy manifest.yaml
- [x] **Hybrid discovery** — builtin (installer) + user (AppData/KALI/skills/)

**Catalog integration (6.2):**
- [x] **Multi-source registry** (`kernel/skills/catalog.py`):
  - [anthropics/skills](https://github.com/anthropics/skills) — official Anthropic
  - [microsoft/skills](https://github.com/microsoft/skills) — 128 Azure SDK skills
  - [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) — 1100+ community
  - `github.com/VasilyKolbenev/kali-skills` — KALI-curated
- [x] **GitHub tarball install** — no git dependency, AST safety gate on scripts
- [x] **Caching** — 1h TTL on-disk in AppData/catalog-cache, GITHUB_TOKEN support
- [x] **Atomic install** with rollback on failure
- [x] **Trust levels** — official / verified / community

**Publish flow (6.3):**
- [x] `kali publish <skill>` CLI — validate + AST safety + .tar.gz bundle
- [x] UI Upload button with PublishDialog (errors/warnings/next-steps)
- [x] Auto-instructions for GitHub PR workflow
- [x] Provenance metadata (source repo, ref, SHA) — spec compliant

**Runtime enforcement (6.4):**
- [x] **SandboxBackend Protocol** — pluggable interface
  * InProcessSandbox (current default)
  * Future: DockerSandbox, CubeVMSandbox, E2BSandbox (KALI Cloud Phase 10)
- [x] **PermissionEnforcer** wired at dispatch (403 on denial)
- [x] **RateLimiter** wired at dispatch (429 on exceed, 120/min default)
- [x] **AuditLog** — SQLite append-only, 30-day retention
- [x] **GET /sandbox/{health,audit,stats}** — inspection endpoints

**UI (6.5):**
- [x] Agent Store tabs (Installed / Anthropic / Microsoft / VoltAgent / KALI)
- [x] Trust badges, live search, install/uninstall with feedback toasts
- [x] Publish dialog with validation errors + next-step instructions
- [x] Typed API client + TypeScript types

**Tests:** 124 passing (skills + plugin_registry + sandbox).

### Phase 7: Integrations 🟡 PARTIAL
- [x] JARVIS pre-recorded voice clips (greet, ok, reply — 17 clips)
- [x] Numbers-to-words for TTS (Russian numerals)
- [x] Server-side audio playback (sounddevice)
- [x] 5 new agents: Notion, Todoist, GitHub, News, Currency
- [~] Home Assistant (agent exists, needs real HA instance)
- [~] Claude Code (agent exists, basic explain/review)
- [ ] Google Calendar sync (agent exists, needs OAuth)
- [ ] Garmin/Apple Health
- [ ] Banking APIs

### Phase 8: Desktop Distribution 🔧 IN PROGRESS
- [x] PyInstaller backend (kali-backend.exe, 293 MB)
- [x] Tauri desktop (kali-desktop.exe, 15 MB)
- [x] NSIS all-in-one installer (933 MB: backend + frontend + models)
- [x] Auto-start backend from Tauri (PID guard, single instance)
- [x] AppData for writable data + .env (Program Files read-only)
- [x] multiprocessing.freeze_support() (prevents fork bomb)
- [x] Background model loading (non-blocking startup)
- [ ] E2E verification on clean Windows install
- [ ] Auto-download voice models on first launch (progress bar)
- [ ] Auto-update mechanism
- [ ] Code signing (Windows SmartScreen)

### Phase 8.5: Voice Pipeline Polish 🔧 IN PROGRESS
- [x] Wake word "Hey Jarvis" (OpenWakeWord, threshold 0.3)
- [x] Audio buffering for OpenWakeWord (1280 sample minimum)
- [x] Thread-safe audio queue (queue.Queue, not asyncio.Queue)
- [x] Anti-echo (mic stops during TTS playback)
- [x] LISTENING timeout (3s, prevents infinite hang)
- [x] TTS sentence splitting for long LLM responses
- [x] Silero VAD cache fix (PermissionError on Windows)
- [ ] Voice quality A/B testing (pitch shift, speaker variants)
- [ ] Streaming TTS (play while generating next sentence)

### Phase 9: Voice-First Agent Skills UX 📋 NEXT
**Core value-add: голосовой интерфейс к Agent Skills экосистеме.**

- [ ] **Agent Store UI tabs**:
  - 🏛 Official (Anthropic) — 30+ curated skills
  - 🏢 Microsoft — 128 Azure SDK skills
  - 🌟 Community (VoltAgent) — 1100+ verified
  - ⚡ KALI Skills — наш кастом с JARVIS-integration
  - 📦 Installed — локальные
- [ ] **Voice-first discovery**: "Jarvis, найди скилл для Notion" → поиск по frontmatter
- [ ] **Install with one voice command**: "Установи это" → clone + safety gate + deploy
- [ ] **Permission voice approval**: Jarvis читает `allowed-tools`, спрашивает подтверждение
- [ ] **Author profiles** via GitHub (username + avatar + repo stars)
- [ ] **Trust badges** based on source:
  - 🟢 **Official** — from anthropics/, microsoft/, google/, stripe/
  - 🔵 **Verified** — KALI-team reviewed + test suite passing
  - ⚪ **Community** — just passed our Safety Gate
- [ ] **Star ratings** via GitHub Issues (community feedback)
- [ ] **Analytics** — install counts via GitHub API

### Phase 10: Mobile 📋 PLANNED
- [x] Server consolidation (one process, one port)
- [ ] React Native companion app (iOS + Android)
- [ ] Push notifications
- [ ] Background wake word on mobile
- [ ] Cloud relay (Tailscale / Cloudflare Tunnel)

### Phase 11: Hardware 📋 FUTURE
- [ ] Raspberry Pi build
- [ ] Touchscreen UI optimization
- [ ] Audio I/O hardware optimization
- [ ] Starlink / satellite connectivity support
- [ ] Custom KALI device prototype

---

## Competitive Positioning

### Our Moat: Voice-First Client for Agent Skills Ecosystem

**KALI не конкурирует со Skills экосистемой — мы её лучший voice-first клиент.** Claude Code, Cursor, Copilot работают со SKILL.md в режиме coding-assistant. KALI даёт эти же скиллы **обычным людям через голос**.

| | KALI | Claude Code | Cursor | Siri/Alexa | AI New World |
|--|------|-------------|--------|------------|--------------|
| Voice-first UX | ✅ Wake word + JARVIS | ❌ CLI | ❌ Editor | ✅ | ✅ |
| Agent Skills compatible | ✅ Native | ✅ Native | ✅ | ❌ | ❌ |
| Custom voice (JARVIS) | ✅ F5/ElevenLabs clone | ❌ | ❌ | ❌ | ❌ |
| Standard interop | ✅ Open spec | ✅ | ✅ | ❌ Walled garden | ❌ |
| For non-developers | ✅ No-code UI | ❌ Developer tool | ❌ Developer tool | ✅ | ✅ |
| Marketplace | ✅ 1100+ skills | ✅ | ✅ | Closed App Store | ❌ |
| Local-first | ✅ Offline ready | ✅ | 🟡 Cloud default | ❌ | ❓ |
| Open source core | ✅ | ❌ | ❌ | ❌ | ❌ |

**Key differentiators:**
1. **Voice as primary input** — Claude Code и Cursor текстовые, Siri/Alexa закрытые. KALI = голос + открытая экосистема.
2. **Agent Skills native** — 1100+ готовых скиллов с первого дня работают в KALI
3. **Interoperability** — скиллы созданные в KALI работают в Claude Code, Cursor, VS Code
4. **Desktop + воздух** — полноценный Tauri-десктоп, не CLI
5. **Кастомный JARVIS voice** — F5-TTS клон из Iron Man Sound Pack
6. **Local-first, cloud-enhanced** — F5 на GPU локально, ElevenLabs в облаке
7. **Sandbox transparency** — user видит audit log (что делал каждый скилл, какие отказы), а не "чёрный ящик"

### Strategic narrative (для инвесторов/PR)

> "KALI — это voice-first desktop OS для Agent Skills экосистемы.
> 
> Если Claude Code — это skills для разработчиков в CLI,
> а Cursor — это skills для разработчиков в IDE,
> то KALI — это skills для всех в голосовом интерфейсе.
> 
> Мы строим не новый walled garden, а лучший клиент к открытому стандарту Anthropic."

---

## Key Files

```
kernel/
├── main.py              # FastAPI entry point (port 3005)
├── event_bus.py          # Pub/sub system
├── config_manager.py     # YAML config
├── plugin_registry.py    # Agent discovery
├── agent_builder.py      # Agent/Skill generation
├── models.py             # Pydantic schemas
├── database.py           # SQLite persistence
├── scheduler.py          # Cron-like events
├── llm_router.py         # Intent routing
├── agent_runtime/
│   ├── runtime.py        # Lifecycle manager
│   └── protocols/        # native, http, (mcp)
└── voice/
    ├── pipeline.py       # Voice orchestration
    ├── stt.py            # Speech-to-text
    ├── tts_router.py     # TTS provider router (F5-TTS / ElevenLabs)
    ├── tts_engine_f5.py  # F5-TTS Russian voice clone (local GPU)
    ├── tts_engine_elevenlabs.py  # ElevenLabs cloud engine
    ├── jarvis_sounds.py  # Pre-recorded JARVIS clips
    └── vad.py            # Voice activity detection

agents/
├── _base/agent_base.py   # Shared base class
├── system/               # Time, system info, timers
├── tasks/                # Task management
├── calendar/             # Google Calendar + local
├── life-dashboard/       # Sleep, spending, calories
├── weather/              # Open-Meteo
├── email/                # Gmail
├── telegram/             # Telegram Bot
├── smart-home/           # Home Assistant (stub)
└── coding/               # Claude Code (stub)

ui/src/
├── App.tsx               # Root component
├── components/           # Avatar, Dashboard, Chat, AgentPanel
├── api/                  # client.ts, websocket.ts
└── stores/               # Zustand state

models/                   # Voice models (gitignored, downloaded on install)
├── f5_tts/               # F5-TTS Russian checkpoints
├── faster_whisper/       # STT models (base.en / large-v3)
└── openwakeword/         # Wake word ONNX models

config/kali.yaml          # Main configuration
```

---

*Last updated: 2026-04-19*
*Version: 0.5.0 — Agent Skills native + Sandbox hardening*

**Stats:**
- 124 passing unit tests
- 15 built-in skills (all SKILL.md compliant)
- 4 catalog sources wired (anthropic/microsoft/voltagent/kali)
- 2 TTS engines (F5-TTS local GPU + ElevenLabs cloud)
- 2 installer variants (Lite 104 MB / Premium 3.4 GB)
