# KALI — Personal AI Operating System

> Your personal AI in your pocket. Manages your life, learns your habits, builds what you need — by voice.

---

## Mission

Дать каждому человеку персонального AI-ассистента, который учится, адаптируется и расширяется голосовыми командами. Пользователь говорит что хочет — система создаёт, тестирует и запускает. Лучшие решения попадают в маркетплейс и помогают другим.

**KALI — это не просто ассистент. Это операционная система для жизни.** Как iOS дала людям App Store для приложений, KALI даёт Agent Store для AI-агентов. Только здесь не нужно быть программистом — достаточно голоса.

## Core Principles

1. **Voice-first** — всё управляется голосом, UI вторичен
2. **No-code by default** — любой человек без опыта может создать агента
3. **Agent-first architecture** — всё есть агент или skill
4. **Local-first, cloud-enhanced** — работает офлайн, облако усиливает
5. **Open ecosystem** — маркетплейс, community, open-source ядро
6. **Safe by design** — песочница, permissions, code review

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
- **Голос** — JARVIS по умолчанию, кастомные голоса через RVC
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
│  │  Mic → VAD → Wake Word → STT → LLM Router → TTS     │   │
│  │       (Silero VAD)  (Whisper) (Claude)  (Silero+RVC) │   │
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

## Dual Model: Skills & Agents

### Skills — лёгкие, декларативные, безопасные

Skills описываются YAML-конфигом без пользовательского кода. Работают через встроенные шаблоны. Sandbox не нужен — нет исполняемого кода, только параметры.

**Встроенные шаблоны:**
- **tracker** — отслеживание значений (вода, калории, расходы, привычки)
- **monitor** — периодическая проверка URL/API с алертами
- **notifier** — уведомления по условиям/расписанию
- **reminder** — напоминания с повторами
- **logger** — запись событий с аналитикой

**Пример skill.yaml:**
```yaml
name: water-tracker
template: tracker
display_name: "Трекер воды"
config:
  unit: "мл"
  daily_goal: 2000
  reminders:
    interval_hours: 2
    message: "Время выпить воды!"
  tracking:
    daily_summary: true
    weekly_chart: true
```

### Agents — полноценные, с кодом, в песочнице

Agents содержат Python-код, сгенерированный LLM. Запускаются в subprocess-песочнице с permission-моделью. Могут использовать API, файлы, другие агенты.

**Жизненный цикл агента:**
```
Идея → Voice Wizard → LLM Generation → Safety Gate → Permission Approval → Deploy → Run
```

### Voice Wizard решает что создавать

Jarvis анализирует запрос и автоматически определяет: это Skill (простой, шаблонный) или Agent (сложный, нужен код). Пользователь не знает разницу — для него это одна команда.

```
"Напоминай пить воду каждые 2 часа"     → Skill (reminder template)
"Отслеживай мой сон и строй графики"    → Skill (tracker template)
"Парси Aviasales и ищи дешёвые билеты"  → Agent (нужен код + network)
"Интегрируй мой Home Assistant"         → Agent (нужен код + network + devices)
```

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

### JARVIS Voice (Production, 2026-04-13)

```
Text → Silero TTS v4 (CPU, ~60ms)
     → ONNX RVC jarvis_v2 (DirectML GPU, ~570ms)
     → EQ Post-Processing (matched to JARVIS Sound Pack)
     → Audio Output (40kHz)
```

**Настройки голоса (FINAL1):**
- Model: `jarvis_v2.onnx` (400 epochs, 52-file Sound Pack)
- FAISS index: `jarvis_v2.index`, influence=0.8
- Pitch shift: +5 semitones
- EQ: low cut <800Hz, mid boost 800-2kHz, presence kill 4-6kHz

### Full Voice Loop

```
Mic → Silero VAD → Wake Word ("Jarvis")
    → faster-whisper STT (~200ms)
    → LLM Router (Claude / Ollama)
    → Agent Dispatch → Response
    → Silero + RVC TTS (~650ms)
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
- **ONNX Runtime (DirectML)** — GPU inference для голоса

### Frontend (Shell)
- **Tauri 2.x** — desktop wrapper (Rust)
- **React 19** — UI framework
- **TypeScript** — типизация
- **Three.js / React-Three-Fiber** — 3D avatar
- **Zustand** — state management
- **Tailwind CSS** — стили

### Voice
- **Silero TTS v4** — синтез речи (CPU)
- **RVC ONNX (jarvis_v2)** — голосовая конверсия (GPU)
- **faster-whisper** — распознавание речи
- **Silero VAD** — детекция голоса
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
- [x] Silero TTS + ONNX RVC pipeline
- [x] SSML markup (abbreviations, stress, prosody)
- [x] RVC jarvis_v2 training + ONNX export
- [x] EQ post-processing matched to Sound Pack
- [x] DirectML GPU acceleration
- [x] Single-process TTS server (no WSL dependency)

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
- [x] Skill template engine (tracker, monitor, notifier, reminder, logger)
- [x] SkillExecutor (in-process, no subprocess)
- [x] Dynamic cron scheduler (croniter)
- [x] AgentBuilder v2 (LLM-powered code generation via Claude API)
- [x] Intent Classifier (skill vs agent detection)
- [x] Voice Wizard (guided creation with questions)
- [x] Permission Enforcer (sandbox runtime, per-agent approval)
- [x] Code Safety Gate (true AST analysis, not string matching)
- [x] Network Proxy (JSON-RPC, domain whitelist, rate limiting)
- [x] Filesystem sandbox (path traversal protection)
- [ ] Agent-to-agent communication (v2.5)

### Phase 6: Cloud Catalog ✅ DONE (local mode)
- [x] Package format (.kali-agent zip with checksums)
- [x] Local catalog search (scans agents/*/manifest.yaml)
- [x] Install flow (unpack → safety gate → deploy)
- [x] Pack flow (agent dir → .kali-agent)
- [x] Supabase client (ready, needs cloud deployment)
- [ ] Supabase cloud deployment (schema, auth, storage)
- [ ] Publish flow (voice → package → upload to cloud)
- [ ] Ratings & reviews
- [ ] Trust levels (official/verified/community)
- [ ] Author profiles

### Phase 7: Smart Integrations ✅ MOSTLY DONE
- [x] Home Assistant (smart-home agent v2 — REST API with mock fallback)
- [x] Claude Code (coding agent v2 — explain/review/suggest via Claude API)
- [x] JARVIS pre-recorded voice clips (greet, ok, reply, thanks — 17 clips)
- [x] Numbers-to-words for TTS (Russian numerals)
- [x] Server-side audio playback (sounddevice, no browser dependency)
- [ ] Google Calendar sync (agent exists, needs OAuth setup)
- [ ] Garmin/Apple Health
- [ ] Banking APIs
- [ ] Notion/Obsidian

### Phase 8: Desktop Distribution 🔧 IN PROGRESS
- [x] PyInstaller backend (kali-backend.exe, 292 MB)
- [x] Tauri desktop (kali-desktop.exe, 13 MB)
- [x] NSIS installer (WebView2 auto-install, desktop shortcut)
- [x] Auto-start backend from Tauri (find_backend in 4 locations)
- [x] AppData for writable data (DB, models — Program Files is read-only)
- [x] Model downloader for first run
- [ ] PyInstaller backend E2E verification on clean install
- [ ] Auto-download ONNX voice models on first launch (progress bar in UI)
- [ ] Installer version bumping + auto-update mechanism

### Phase 9: Mobile 📋 PLANNED
- [ ] Server consolidation (one process, one port) ✅ DONE
- [ ] React Native app (iOS + Android)
- [ ] Push notifications
- [ ] Background microphone (wake word)
- [ ] Cloud relay (Tailscale / Cloudflare Tunnel)

### Phase 10: Hardware 📋 FUTURE
- [ ] Raspberry Pi build
- [ ] Touchscreen UI optimization
- [ ] Audio I/O hardware optimization
- [ ] CLIK device prototype

---

## Competitive Positioning

### Our Moat: AI OS + Agent Marketplace

| | KALI | AI New World | Siri/Alexa | Open Interpreter |
|--|------|-------------|------------|-----------------|
| Voice-first | ✅ | ✅ | ✅ | ❌ |
| Custom agents | ✅ Voice-built | ❌ | ❌ | ❌ |
| Marketplace | ✅ Cloud catalog | ❌ | App Store (closed) | ❌ |
| Open source | ✅ Core open | ❌ | ❌ | ✅ |
| Local-first | ✅ Offline capable | ❓ | ❌ Cloud-only | ✅ |
| Desktop app | ✅ Tauri | ❓ | ❌ | ✅ Terminal |
| Custom voice | ✅ JARVIS RVC | ❌ | ❌ | ❌ |

**Key differentiators:**
1. Любой пользователь создаёт агентов голосом — без кода
2. Маркетплейс — экосистема растёт силами community
3. Кастомный голос — не generic TTS, а обученный JARVIS
4. Local-first — работает без интернета, облако усиливает
5. Open-source ядро — доверие и вклад сообщества

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
    ├── tts.py            # Text-to-speech routing
    └── vad.py            # Voice activity detection

services/tts/
├── server.py             # Silero + ONNX RVC server (port 3002)
└── rvc_onnx.py           # ONNX RVC inference engine

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

models/                   # ONNX voice models
├── jarvis_v2.onnx        # RVC voice model
├── jarvis_v2.index       # FAISS index
├── vec-768-layer-12.onnx # HuBERT features
└── rmvpe.onnx            # Pitch estimator

config/kali.yaml          # Main configuration
```

---

*Last updated: 2026-04-13*
*Version: 0.2.0*
