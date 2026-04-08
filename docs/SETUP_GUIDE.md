# Jarvis 2026 — Setup & Testing Guide

## Step 0: Prerequisites

Needs to be installed on your laptop:
- **Python 3.12+** — https://python.org/downloads
- **Node.js 20+** — https://nodejs.org
- **Git** — https://git-scm.com

Check in terminal:
```bash
python --version   # 3.12+
node --version     # 20+
git --version
```

---

## Step 1: Install Dependencies

Open terminal in the Jarvis folder:

```bash
cd Desktop/Jarvis

# Install uv (Python package manager)
pip install uv

# Install Python deps
uv sync --all-extras

# Install pnpm (Node package manager)
npm install -g pnpm

# Install UI deps
cd ui && pnpm install && cd ..
```

Expected: no errors, all packages installed.

---

## Step 2: Run Tests (verify everything works)

```bash
uv run pytest -v
```

Expected: **191 passed** in green. If something fails — check Python version (needs 3.12+).

---

## Step 3: Create .env File

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in what you have:

```bash
# REQUIRED for Claude AI features:
ANTHROPIC_API_KEY=sk-ant-...your-key...

# OPTIONAL — Telegram bot:
# TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
# TELEGRAM_CHAT_ID=your-chat-id
```

If you don't have an Anthropic key yet — everything works, just LLM calls will fail gracefully.

---

## Step 4: Start the Backend (Kernel)

```bash
uv run uvicorn kernel.main:create_app --factory --reload --port 8000
```

You should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Leave this terminal **running**. Open a **new terminal** for the next steps.

---

## Step 5: Test Backend API

Open a new terminal and run:

```bash
# Health check
curl http://localhost:8000/health

# List agents
curl http://localhost:8000/agents

# Voice status
curl http://localhost:8000/voice/status

# Config
curl http://localhost:8000/config
```

Or open these URLs in your browser — you'll see JSON responses.

---

## Step 6: Start the Frontend (UI)

In the new terminal:

```bash
cd ui
pnpm dev
```

You should see:
```
VITE ready in 300ms
➜  Local: http://localhost:1420/
```

---

## Step 7: Open UI in Browser

Open **http://localhost:1420** in Chrome/Firefox.

You should see:
- **Left sidebar** with mode buttons (Focus, Dashboard, Agents, Night)
- **Center** — animated 3D blue blob (AI Avatar)
- **Bottom** — "Ready" text (Voice Visualizer)
- **Red dot** in sidebar (kernel not connected via WebSocket yet — normal if CORS needs a refresh)

### Test each mode:

1. **Focus Mode** (default) — blob avatar + voice status
2. **Dashboard** (click grid icon) — 6 widgets: Sleep 7.2h, Tasks 5/8, Team call, $340, 1,800 kcal, 0 agents
3. **Agents** (click gear icon) — list of agents with Start/Stop buttons
4. **Nightstand** (click moon icon) — big digital clock + date

---

## Step 8: Test API Endpoints (Advanced)

While both kernel and UI are running:

### Morning Briefing
```bash
curl http://localhost:8000/briefing/morning
```
Returns: daily digest text.

### Budget
```bash
# Set a food budget
curl -X POST http://localhost:8000/budget/goal \
  -H "Content-Type: application/json" \
  -d '{"category": "food", "limit": 500}'

# Log an expense
curl -X POST http://localhost:8000/budget/expense \
  -H "Content-Type: application/json" \
  -d '{"amount": 45, "category": "food"}'

# Check goals
curl http://localhost:8000/budget/goals
```

### Focus Timer
```bash
# Start 25-min focus session
curl -X POST http://localhost:8000/focus/start \
  -H "Content-Type: application/json" \
  -d '{"duration_minutes": 25, "label": "coding"}'

# Check status
curl http://localhost:8000/focus/status

# Stop early
curl -X POST http://localhost:8000/focus/stop
```

### Create Custom Agent (No-Code Builder!)
```bash
# Create a price monitor agent from template
curl -X POST http://localhost:8000/agents/create \
  -H "Content-Type: application/json" \
  -d '{"name": "my-monitor", "description": "My custom monitor", "template": "monitor"}'

# List custom agents
curl http://localhost:8000/agents/custom

# Delete it
curl -X DELETE http://localhost:8000/agents/custom/my-monitor
```

### Notifications
```bash
# Send a notification
curl -X POST http://localhost:8000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "message": "Hello from Jarvis!"}'

# Check pending
curl http://localhost:8000/notifications/pending
```

### Load & Use an Agent
```bash
# Load system agent
curl -X POST http://localhost:8000/agents/system/load

# Check it's running
curl http://localhost:8000/agents/running

# Check status
curl http://localhost:8000/agents/system/status

# Unload
curl -X POST http://localhost:8000/agents/system/unload
```

---

## Step 9: Setup Telegram Bot (Optional)

1. Open Telegram, find **@BotFather**
2. Send `/newbot`, follow instructions, get your **bot token**
3. Send a message to your new bot
4. Open: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Find your **chat_id** in the response
6. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234...
   TELEGRAM_CHAT_ID=987654321
   ```
7. Restart kernel (Ctrl+C, re-run uvicorn)
8. Test: load telegram agent, it will be able to send you messages

---

## Step 10: Setup Google Calendar + Gmail (Optional)

1. Go to https://console.cloud.google.com
2. Create a new project
3. Enable **Google Calendar API** and **Gmail API**
4. Create OAuth 2.0 credentials (Desktop app type)
5. Download the JSON file
6. Save it as `data/google_credentials.json`
7. Restart kernel — first time it will open browser for Google login
8. After login, `data/google_token.json` is created automatically
9. Calendar agent will now use real Google Calendar data

---

## Step 11: Weather Test (works immediately, no setup!)

```bash
# Load weather agent
curl -X POST http://localhost:8000/agents/weather/load

# Wait 2 seconds, then check status
curl http://localhost:8000/agents/weather/status
```

Note: The weather agent uses Open-Meteo API (free, no key needed) but needs to be dispatched through the agent runtime to actually call `get_weather`. Direct agent subprocess testing:

```bash
echo '{"jsonrpc":"2.0","method":"initialize","params":{"config":{}},"id":1}' | python agents/weather/agent.py
```

Then in a separate line:
```bash
echo '{"jsonrpc":"2.0","method":"execute","params":{"action":"get_weather","args":{"city":"Moscow"}},"id":2}' | python agents/weather/agent.py
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uv: command not found` | `pip install uv` or check PATH |
| `pnpm: command not found` | `npm install -g pnpm` |
| Port 8000 already in use | Kill old process or use `--port 8001` |
| CORS errors in browser | Refresh page, kernel has CORS configured |
| Tests fail | Check Python version `python --version` (need 3.12+) |
| Red dot in sidebar | Normal — WebSocket auto-reconnects every 3s |
| Google auth error | Make sure `data/google_credentials.json` exists |

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `uv run pytest -v` | Run all 191 tests |
| `uv run uvicorn kernel.main:create_app --factory --reload --port 8000` | Start backend |
| `cd ui && pnpm dev` | Start frontend |
| `uv run ruff check kernel/ tests/ agents/` | Lint Python |
| `cd ui && npx tsc --noEmit` | TypeScript check |
