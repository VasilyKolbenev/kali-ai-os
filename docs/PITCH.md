# KALI — Pitch

## One-liner

AI operating system that replaces apps with agents.

## Problem

People use 10+ apps daily — calendar, tasks, email, budget, notes, smart home. Every app is a separate login, separate UI, separate mental model. AI assistants (Siri, Alexa) answer questions but don't take action. Rabbit R1 ($199) and Humane AI Pin ($699) tried to solve this and both failed — broken integrations, closed ecosystems, hardware that couldn't be updated.

## Solution

KALI is a voice-first AI OS where everything runs through **agents** — modular, composable, extensible units of automation. Instead of opening apps, you speak naturally and the system executes.

The key insight: **apps are the wrong abstraction for AI**. Agents are the right one.

## Why Now

- LLMs reached usable quality for real task execution (GPT-4o, Claude)
- Local models became viable (Llama 3 on consumer hardware via Ollama)
- Voice interfaces matured (Whisper-level STT, natural TTS)
- Users are overwhelmed by tool fragmentation
- Previous AI devices failed, creating a clear playbook of what NOT to do

## Product

**Working system** (not a concept):
- 9 built-in agents (calendar, email, tasks, budget, weather, Telegram, smart home, system, coding)
- Voice pipeline (wake word → STT → LLM → agent → TTS)
- No-code agent builder (describe in English → working agent)
- Hybrid AI (70-80% local/free, 20-30% cloud)
- Desktop app with 3D animated avatar
- 193 tests, 28+ API endpoints

## Technology Advantage

**Hybrid AI architecture** is the moat:

| Request type | Runs on | Cost |
|---|---|---|
| Simple commands (time, timer, weather) | Local Llama | $0 |
| Tool calling (calendar, email) | Cloud (Claude/GPT-4o) | ~$0.01 |
| Code generation (agent builder) | Cloud | ~$0.05 |

Competitors route everything through cloud APIs. We route 70-80% locally → dramatically lower cost per user → sustainable unit economics at scale.

## Market

KALI sits at the intersection of three markets:

| Market | Size |
|--------|------|
| Productivity software (Notion, Todoist, Google Workspace) | $50-70B |
| AI assistants & copilots (ChatGPT, Claude, Copilot) | $100B+ by 2030 |
| Smart home devices (Alexa, Google Home) | $30-50B |

We're creating a new category: **AI execution layer** — the operating system between the user and their digital life.

## Competitive Landscape

| | Siri / Alexa | ChatGPT / Claude | Zapier | Rabbit R1 | **KALI** |
|---|---|---|---|---|---|
| Takes action | Limited | No | Yes | Barely | **Yes** |
| Voice-first | Yes | No | No | Yes | **Yes** |
| Extensible | No | Plugins | Yes | No | **Agents** |
| Local AI | No | No | No | No | **Yes** |
| Open ecosystem | No | Limited | Yes | No | **Marketplace** |

Nobody owns the AI execution layer yet.

## Business Model

### Pricing

| Tier | Price | Includes |
|------|-------|----------|
| **Device** | $149 | Hardware + AI OS + 9 agents + Marketplace |
| **Basic** | $9/mo | Local AI + 500 cloud requests + OTA updates |
| **Pro** | $19/mo | Unlimited cloud AI + advanced agents |
| **Ultra** | $29/mo | Everything + Agent Builder + priority support |

### Unit Economics

| Metric | Value |
|--------|-------|
| Device BOM | ~$28 |
| Device margin | ~81% |
| Avg subscription | ~$15/mo |
| AI cost/user | ~$3/mo |
| Subscription margin | ~80% |
| LTV (12 months) | ~$329 |

### Revenue Streams

1. Hardware sales ($149, 81% margin)
2. Cloud subscription ($9-29/mo, ~80% margin)
3. Marketplace fees (15% on premium agents — v2)
4. Enterprise (fleet management, custom agents — v3)

## Go-To-Market

**Phase 1** — AI enthusiasts, developers, productivity power users
- GitHub, Reddit, X (Twitter), YouTube demos
- Desktop software, bring-your-own API key

**Phase 2** — Early mainstream
- Hardware device ($149)
- Plug-and-play experience (no technical setup)
- Agent Marketplace for discovery

**Phase 3** — Scale
- Cloud-managed tier (zero setup)
- Mobile companion app
- Enterprise partnerships

## Moat

1. **Hybrid AI infra** — 70-80% lower AI costs than competitors
2. **Agent ecosystem** — more agents = more value = more users (network effect)
3. **No-code builder** — users create their own agents, increasing stickiness
4. **Local-first privacy** — differentiator vs cloud-only competitors
5. **Marketplace network effects** — developers build for the platform

## What's Built

| Component | Status |
|-----------|--------|
| Kernel (event bus, config, DB, scheduler) | Done |
| Voice pipeline (STT, TTS, VAD, wake word) | Done |
| Agent runtime (JSON-RPC, HTTP, dispatcher) | Done |
| Desktop UI (React + Three.js avatar) | Done |
| 9 built-in agents | Done |
| Google Calendar, Gmail, Telegram | Done |
| Budget, focus timer, routines, briefings | Done |
| No-code agent builder | Done |
| Hardware device | In design |
| Agent Marketplace | Planned |

## Traction

- 193 tests passing
- Complete working prototype (backend + frontend + agents)
- Real integrations (Google, Telegram, weather)
- Hardware design finalized (ESP32-S3 + AMOLED)

## The Ask

Funding for:
- Product polish (consumer-grade UX)
- Hardware prototyping and first production run
- Agent Marketplace launch
- Distribution and community building

## Vision

Computers had Windows.
Phones had iOS.

AI needs an operating system too.

KALI is that system.
