# KALI Positioning — Anchor vs Competition

> **Purpose:** A reference to re-read when feature decisions drift. Not a pitch deck.
> When OpenClaw ships something new and you feel urge to copy — come here first.
>
> Last updated: 2026-04-24.

---

## What KALI is (one sentence)

**KALI is a voice-first AI OS that lets non-technical people *create* their own AI agents by speaking — distributed by what those agents do going viral on TikTok and Reels.**

Jarvis = the assistant persona inside KALI (the voice, the name users say). KALI = the platform (brand, marketplace, kernel).

## What KALI is NOT

- **Not OpenClaw.** OpenClaw is an open-source agent-OS for developers. KALI is a closed, polished product for строитель / врач / офисник 30+.
- **Not Cursor / Raycast / Copilot.** Those are developer productivity tools. KALI's target persona doesn't write code.
- **Not Siri / Alexa.** Those are reactive assistants with fixed skills. KALI is about **creating new agents** on the fly.
- **Not a chatbot.** Jarvis doesn't just talk; the OS **builds and runs** agents that act.
- **Not a skill marketplace for developers.** The marketplace is curated and social (likes, remixes, reels), not a CLI install target.

## Core differentiators (5 pillars that cannot move)

1. **Voice-first for non-tech.** The primary interaction is speaking to Jarvis. Text/CLI/config are fallbacks, not first-class. Every friction point (mic permission, settings, onboarding) must clear the "building worker with grease on his hands" bar.

2. **Agent *creator*, not agent *runner*.** The 60-second test: a non-coder describes an agent out loud and gets a working one they can show friends. If a feature helps dev-authored skills instead, it's OpenClaw's game, not ours.

3. **UGC loop as primary distribution.** Create agent → record reel → friend sees → installs KALI → creates own. Share-to-Reels must be built-in. Success metric: K-factor ≥ 1. Traditional content marketing is secondary.

4. **Platform + Persona brand split.** KALI = platform (marketplace, kernel, UI). Jarvis = persona (voice, character, wake-word). Mirror Apple/Siri, Google/Assistant. *Note: Marvel IP risk on "Jarvis" → rename before public launch (candidates: Kaly, Jay, Nova, Halo, Aria). Memory: project_brand_naming.md.*

5. **Desktop → Mobile → Hardware continuum.** Not software-only. The dedicated device (CLIK + Starlink) is a real product endgame, not a marketing fantasy. Decisions today must leave that door open.

## Tagline candidates (pick later, when landing is being built)

- "JARVIS для вашего дома, а не для IDE."
- "Один голос — и готов агент. Без кодинга, без терминала."
- "OpenClaw — для разработчиков. KALI — для ваших родителей."
- "Создай AI-агента голосом за минуту. Покажи друзьям. Они захотят такого же."
- "Your own Jarvis. Built by voice. Shared in reels."

## Threat watch — when each adjacency becomes a direct hit

| Trigger | Who | Impact | Response |
|---|---|---|---|
| OpenClaw ships a real voice interface | OpenClaw | Direct overlap on UX modality | Double down on non-tech persona polish; emphasise *creation* over *running* |
| OpenClaw ships non-tech onboarding (no terminal / no .env) | OpenClaw | Direct overlap on persona | Escalate UGC distribution + hardware device urgency |
| OpenClaw ships share-to-reels | OpenClaw | Distribution channel contested | Ship first or differentiate through quality of reels-export |
| AI New World ships English version + non-RU traction | AI New World | Direct overlap on everything | Lean on marketplace / agent-builder — they're monolithic |
| Apple / Google ship system-level agent creator | Platform | Category compression | Pivot to hardware device sooner; software-only play compressed |

Check every 2 weeks. If none triggered — no response needed, stay focused on roadmap.

## Decisions already locked (don't re-debate mid-session)

- **Voice-first, not text-first.** Chat input stays secondary.
- **Non-tech persona, not developer persona.** All UI decisions pass "builder with grease on his hands" test.
- **Closed-source polished product, not open-source community.** Rationale: polished non-tech experience cannot be community-driven at our stage. Revisit at Series A+.
- **Russian-first launch, English later.** Market fit first, global later.
- **Desktop app first, mobile + hardware after traction.** Don't parallelise prematurely.
- **Marketplace curated, not open.** Network effects come from quality, not volume.

## Features to resist (OpenClaw territory, losing battle if chased)

- Advanced terminal agent integration (SSH, shell access to remote hosts)
- Developer-facing CLI for skill management
- IDE plugins / integration with VS Code / Cursor
- Unix-philosophy composability of agents (pipe one into another)
- Full headless mode (no UI, run from command line)
- "Power-user" keyboard shortcuts as primary control mode
- Self-hostable server architecture

If one of these feels tempting, re-read Core Differentiators. If still tempting, talk it through — don't just start building.

## Features to double down on (our moat — invest here)

- Voice builder polish (every 100ms of latency matters)
- Non-tech onboarding (mic permissions → first agent in < 3 minutes)
- Settings UI that a 55-year-old can navigate without fear
- Share-to-Reels (1-click record, caption auto-generated, agent QR code embedded)
- Curated Agent Store with social signals (likes, remixes, creator profiles)
- Цифровой статус dashboard — "my life at a glance" angle
- Hardware device roadmap that doesn't rot

## Governance — when to update this doc

- Every significant competitor move (new feature launch, funding round, pivot)
- Every time our positioning shifts (new persona, new market, new pricing tier)
- Before pitch decks, landing pages, or major public copy
- Max every 3 months even if nothing changed — freshness check

Owner: Vasily. Memory agent should flag proposed edits but not apply silently.
