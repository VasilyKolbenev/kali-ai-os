# Jarvis 2026

**Personal AI Command Center** — voice-controlled agent orchestrator that saves you time and money.

A desktop AI assistant inspired by the CLIK device concept. Unlike failed hardware like Rabbit R1, Jarvis 2026 is open-source, runs on your PC, and actually works.

---

## Why Jarvis?

| Problem | How Jarvis Solves It |
|---------|---------------------|
| You check 5 apps every morning | **Morning Briefing** — one voice command gives you calendar, tasks, weather, budget |
| You forget subscriptions eating your money | **Subscription Tracker** — detects recurring charges, suggests what to cancel |
| You lose focus switching between tools | **Focus Timer** — Pomodoro mode blocks distractions, tracks deep work |
| You can't find the right app for a task | **Quick Capture** — say it, AI routes it to the right place automatically |
| You want a custom automation but can't code | **Agent Builder** — describe what you need in plain English, get a working agent |
| Smart assistants are cloud-locked black boxes | **Open source** — runs locally, your data stays on your machine |

### Rabbit R1 vs Jarvis 2026

| | Rabbit R1 ($199) | Jarvis 2026 (Free) |
|---|---|---|
| Apps | 4 (broken) | 9 agents + unlimited custom |
| AI | Fake "LAM" (ChatGPT wrapper) | Real Claude/GPT-4o + local Ollama |
| Battery | ~1 hour | Desktop / always-on server |
| Memory | None | Conversation history across sessions |
| Ecosystem | Closed, dead | Open plugin system, community agents |
| Updates | Hardware can't be fixed | Software updates instantly |
| Source | Proprietary | Open source |

---

## Features

### Save Time
- **Morning Briefing** — automated daily digest (calendar + tasks + weather + budget)
- **Quick Capture** — one phrase, AI routes to tasks/calendar/spending
- **Focus Timer** — Pomodoro with stats and distraction blocking
- **Routines** — chain actions: "morning routine" = briefing + dashboard + lights
- **Weekly Review** — auto-generated productivity report every Sunday
- **Email Digest** — Gmail inbox summary, send emails by voice

### Save Money
- **Budget Goals** — set limits by category, get alerts at 80% and 100%
- **Subscription Tracker** — detect recurring charges in your spending history
- **Spending Analytics** — daily/weekly trends with overspend warnings

### AI-Powered
- **Voice Control** — wake word "Jarvis" + natural speech commands
- **LLM Router** — Claude API or OpenAI for complex tasks, local Ollama for fast/private ones
- **Conversation Memory** — Jarvis remembers context across sessions
- **No-Code Agent Builder** — create custom agents by describing them in plain English

### Integrations
- **Google Calendar** — real events with local fallback
- **Gmail** — check inbox, send emails, search
- **Telegram Bot** — remote control + notifications on your phone
- **Weather** — Open-Meteo (free, no API key)
- **Home Assistant** — smart home control (v2)

### Hardware-Ready
- Architecture designed for future embedded device (Raspberry Pi / ESP32-S3)
- Kernel separated from UI — runs headless on any server
- ESP32-S3 with round 1.28" touchscreen as thin WiFi client

---

## Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Kernel | Python 3.12+ / FastAPI |
| Database | SQLite (async via aiosqlite) |
| Event System | Async pub/sub with wildcard topics |
| LLM | Anthropic Claude / OpenAI GPT-4o / Ollama (local) |
| STT | faster-whisper (CTranslate2) |
| TTS | Piper TTS |
| VAD | Silero VAD + energy fallback |
| Wake Word | OpenWakeWord |
| Agent Protocol | JSON-RPC 2.0 (stdin/stdout) |

### Frontend
| Component | Technology |
|-----------|-----------|
| Desktop Shell | Tauri 2.x (Rust) |
| UI Framework | React 19 + TypeScript |
| 3D Avatar | Three.js / React Three Fiber (GLSL shaders) |
| State | Zustand |
| Styling | Tailwind CSS 4 |
| Real-time | WebSocket |

### Architecture

```
┌─────────────────────────────────────────────────┐
│                 TAURI SHELL                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ 3D Avatar│ │Dashboard │ │  Agent Panel     │ │
│  │ (WebGL)  │ │(Widgets) │ │  (load/unload)   │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
│              WebSocket / Tauri IPC               │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│             PYTHON KERNEL (FastAPI)              │
│                                                  │
│  Event Bus ── Config ── Database ── Scheduler    │
│  LLM Router ── Memory ── Notifications           │
│  Budget ── Focus Timer ── Routines ── Briefing   │
│  Agent Builder ── Plugin Registry                │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │              Agent Runtime                   │ │
│  │  system │ tasks │ calendar │ email │ weather │ │
│  │  telegram │ life-dashboard │ smart-home      │ │
│  │  coding │ custom/*                           │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │            Voice Pipeline                    │ │
│  │  Mic → VAD → Wake Word → STT → LLM → TTS   │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

---

## Quick Start

### Windows
```bash
# Double-click start.bat — it does everything automatically
start.bat
```

### Manual Setup
```bash
# Install
pip install uv
uv sync --all-extras
npm install -g pnpm
cd ui && pnpm install && cd ..

# Configure
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY or OPENAI_API_KEY

# Run
uv run uvicorn kernel.main:create_app --factory --reload --port 8000  # terminal 1
cd ui && pnpm dev                                                       # terminal 2

# Open http://localhost:1420
```

### Verify
```bash
uv run pytest -v   # 193 tests
```

---

## Configuration

### LLM Provider

Edit `config/jarvis.yaml`:

```yaml
llm:
  cloud_provider: "openai"       # "anthropic" or "openai"
  cloud_model: "gpt-4o"          # or "claude-sonnet-4-20250514"
```

And set the API key in `.env`:
```bash
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
```

### Telegram Bot
1. Create bot via @BotFather in Telegram
2. Add to `.env`:
```bash
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
```

### Google Calendar / Gmail
1. Create project at console.cloud.google.com
2. Enable Calendar API + Gmail API
3. Download OAuth credentials → `data/google_credentials.json`
4. First run opens browser for Google login

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | System health + component status |
| `/config` | GET | Current configuration |
| `/agents` | GET | All registered agents |
| `/agents/tools` | GET | LLM function calling tools |
| `/agents/running` | GET | Currently loaded agents |
| `/agents/{name}/load` | POST | Start an agent |
| `/agents/{name}/unload` | POST | Stop an agent |
| `/agents/{name}/status` | GET | Agent health check |
| `/agents/create` | POST | Create custom agent (no-code builder) |
| `/agents/custom` | GET | List custom agents |
| `/voice/status` | GET | Voice pipeline state |
| `/voice/start` | POST | Start listening |
| `/voice/stop` | POST | Stop listening |
| `/briefing/morning` | GET | Generate morning briefing |
| `/budget/goal` | POST | Set budget limit |
| `/budget/goals` | GET | All budget goals + progress |
| `/budget/expense` | POST | Log an expense |
| `/focus/start` | POST | Start focus timer |
| `/focus/stop` | POST | Stop focus timer |
| `/focus/status` | GET | Timer status |
| `/routines` | GET | List routines |
| `/routines/{name}/execute` | POST | Run a routine |
| `/notifications/send` | POST | Send notification |
| `/notifications/pending` | GET | Pending notifications |
| `/ws` | WebSocket | Real-time events |

---

## Creating Custom Agents

### From Template (API)
```bash
curl -X POST http://localhost:8000/agents/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "btc-price",
    "description": "Bitcoin price monitor",
    "template": "monitor"
  }'
```

Templates: `monitor` (periodic checks), `tracker` (value tracking), `notifier` (alert system).

### From Code
```bash
curl -X POST http://localhost:8000/agents/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "description": "My custom agent",
    "tools": [{"name": "do_thing", "description": "Does the thing", "parameters": {}}],
    "code": "if action == \"do_thing\":\n    return {\"result\": \"done\"}\nelse:\n    raise ValueError(f\"Unknown: {action}\")"
  }'
```

---

## Project Structure

```
jarvis/
├── kernel/                    # Python backend
│   ├── main.py                # FastAPI app (28+ endpoints)
│   ├── event_bus.py           # Async pub/sub
│   ├── config_manager.py      # YAML config + hot-reload
│   ├── database.py            # SQLite persistence
│   ├── llm_router.py          # Claude / OpenAI / Ollama
│   ├── memory.py              # Conversation history
│   ├── notifications.py       # Desktop + Telegram alerts
│   ├── briefing.py            # Morning / weekly reports
│   ├── budget.py              # Spending goals + alerts
│   ├── focus.py               # Pomodoro timer
│   ├── routines.py            # Action sequences
│   ├── agent_builder.py       # No-code agent generator
│   ├── voice/                 # Voice pipeline
│   └── agent_runtime/         # Agent process manager
├── agents/                    # Agent plugins
│   ├── system/                # Time, info, timers
│   ├── tasks/                 # Todo management
│   ├── calendar/              # Google Calendar
│   ├── email/                 # Gmail
│   ├── telegram/              # Telegram bot
│   ├── weather/               # Open-Meteo
│   ├── life-dashboard/        # Sleep, spending, energy
│   ├── smart-home/            # Home Assistant
│   ├── coding/                # Code assistant
│   └── custom/                # User-created agents
├── ui/                        # React frontend
│   └── src/
│       ├── components/Avatar/ # Three.js 3D blob
│       ├── components/Dashboard/
│       └── stores/            # Zustand state
├── config/jarvis.yaml         # Main config
├── start.bat                  # One-click launcher
└── tests/                     # 193 tests
```

---

## Stats

| Metric | Value |
|--------|-------|
| Tests | 193 |
| Commits | 70 |
| Python files | 84 |
| TypeScript files | 25 |
| API endpoints | 28+ |
| Built-in agents | 9 |
| Kernel services | 16 |
| Lines of code | ~6,000 |

---

## Roadmap

- [x] Core Kernel (event bus, config, database, scheduler)
- [x] Voice Pipeline (STT, TTS, VAD, wake word)
- [x] Agent Runtime (JSON-RPC, HTTP protocols)
- [x] UI Shell (React + Three.js avatar)
- [x] 9 Built-in Agents
- [x] Real API Integrations (Google, Gmail, Telegram)
- [x] Saving Features (budget, focus, briefings, routines)
- [x] No-Code Agent Builder
- [x] OpenAI / Anthropic dual support
- [ ] UI Polish (CLIK-level design, animations)
- [ ] Tauri production build (.exe installer)
- [ ] ESP32-S3 firmware (thin client)
- [ ] 3D printed hardware case
- [ ] Agent marketplace (community sharing)
- [ ] Multi-language (Russian, Ukrainian, English)
- [ ] Mobile companion app

---

## License

Private repository. All rights reserved.
