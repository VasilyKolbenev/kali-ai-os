# KALI

**AI operating system that replaces apps with agents.**

One voice command. Calendar, tasks, email, budget, smart home — handled.

```
"KALI, start my day"

→ 3 meetings today. First: Team call at 10am.
→ 5 tasks pending, 2 high priority.
→ Weather: 22°C, clear.
→ Budget: $320 remaining this week.
```

---

## What KALI Does

Instead of opening apps, you give commands. KALI routes them to the right **agent** and executes.

| You say | What happens |
|---------|-------------|
| "Schedule a meeting tomorrow at 2pm" | Calendar agent creates the event |
| "Track $20 for lunch" | Budget agent logs it, checks your limit |
| "Focus for 25 minutes" | Focus timer starts, notifications muted |
| "What's in my inbox?" | Email agent summarizes Gmail |
| "Create an agent to monitor BTC price" | Agent Builder generates it — no code needed |

---

## How It Works

**Hybrid AI** — most requests run on a local model (free, private). Complex tasks go to cloud AI (Claude or GPT-4o). You control the balance.

**Agent architecture** — every capability is a modular agent. Install new ones, create your own, or share with the community through the Agent Marketplace.

**Voice-first** — wake word "jarvis", natural speech, real-time response. Full pipeline: mic → VAD → wake word → STT → LLM → agent → TTS → speaker.

---

## Built-in Agents

| Agent | What it does |
|-------|-------------|
| **Calendar** | Google Calendar integration with local fallback |
| **Tasks** | Todo management with priorities and progress |
| **Email** | Gmail — inbox summary, send, search |
| **Budget** | Spending limits, alerts at 80%/100%, subscription detection |
| **Focus** | Pomodoro timer with session tracking |
| **Weather** | Current conditions and 3-day forecast |
| **Telegram** | Remote control and notifications |
| **Smart Home** | Home Assistant integration |
| **System** | Time, timers, system info |

Plus: **Morning Briefing**, **Weekly Review**, **Routines** (automated action chains).

---

## Create Your Own Agents

Describe what you need — KALI builds it:

```
"Create an agent that checks USD/RUB exchange rate every morning
 and sends me a Telegram message if it changes more than 1%"
```

Or use templates via API:

```bash
curl -X POST localhost:8000/agents/create \
  -d '{"name": "btc-monitor", "description": "Bitcoin price alerts", "template": "monitor"}'
```

Templates: `monitor`, `tracker`, `notifier` — or write custom logic.

---

## Quick Start

**Windows:** double-click `start.bat`

**Manual:**
```bash
pip install uv && uv sync --all-extras          # Python deps
npm install -g pnpm && cd ui && pnpm install     # UI deps
cp .env.example .env                             # Add your API key

# Terminal 1: backend
uv run uvicorn kernel.main:create_app --factory --reload --port 8000

# Terminal 2: frontend
cd ui && pnpm dev

# Open http://localhost:1420
```

Supports **OpenAI** or **Anthropic** — set your preferred provider in `config/kali.yaml`.

---

## Architecture

```
┌─────────────────────────────────────┐
│          Desktop UI (Tauri)         │
│   3D Avatar · Dashboard · Agents   │
│           WebSocket ↕               │
├─────────────────────────────────────┤
│        Python Kernel (FastAPI)      │
│                                     │
│  Voice Pipeline · LLM Router       │
│  Event Bus · Memory · Scheduler    │
│  Budget · Focus · Routines         │
│  Agent Builder · Notifications     │
│                                     │
│  ┌─────────────────────────────┐   │
│  │       Agent Runtime         │   │
│  │  9 built-in + custom agents │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

**Backend:** Python 3.12, FastAPI, SQLite, WebSocket
**Frontend:** React 19, Three.js (3D avatar), Tailwind, Zustand
**Voice:** faster-whisper, Piper TTS, Silero VAD, OpenWakeWord
**AI:** Claude / GPT-4o / Ollama (local)
**Desktop:** Tauri 2.x (Rust)

---

## Integrations

| Service | Status |
|---------|--------|
| Google Calendar | Working (OAuth) |
| Gmail | Working (OAuth) |
| Telegram | Working (Bot API) |
| Weather (Open-Meteo) | Working (no key needed) |
| Home Assistant | Stub (v2) |
| Spotify, Notion | Planned |

---

## Project Status

| | |
|---|---|
| Tests | 193 passing |
| API endpoints | 28+ |
| Built-in agents | 9 |
| Voice pipeline | Implemented |
| Desktop UI | Working |

See the full [Setup Guide](docs/SETUP_GUIDE.md) for detailed instructions.

---

## Roadmap

- [x] Core kernel, voice pipeline, agent runtime
- [x] Desktop UI with 3D avatar
- [x] Google Calendar, Gmail, Telegram integrations
- [x] Budget tracking, focus timer, routines
- [x] No-code agent builder
- [ ] UI polish and animations
- [ ] Hardware device (ESP32-S3 + AMOLED)
- [ ] Agent Marketplace
- [ ] Mobile companion app

---

## License

Proprietary software. All rights reserved.
Agent SDK and marketplace are open for community development.
