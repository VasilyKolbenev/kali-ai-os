# KALI — Next-Work Plan (forward items, 2026-07-01)

Recorded per Vasily so nothing is lost across sessions. These are **planned, not built**. Each gets its own brainstorm → spec → plan → TDD cycle when picked up.

---

## A. User profile questionnaire ("анкета") — DESIGN APPROVED, not built

**Concept:** an optional short onboarding questionnaire so Jarvis knows the user and addresses them correctly. Fields (all skippable): **имя · пол · род занятий · город · возраст-диапазон**. Each field → a fact in memory → the persona adapts **address** (name), **grammar** (gender: «ты уверена?/уверен?»), **tone/vocabulary** (occupation: simpler for a builder, more clinical for a doctor), **local context** (city → weather). Input = **hybrid**: UI form (gender = 2 buttons, occupation/age = chips, name/city = text) + a per-field "сказать голосом" button (enabled only when STT is ready → honest degradation).

**Grounding (infra already exists):**
- Desktop: `kernel/database.py:233 save_user_fact(topic, fact, confidence)` + `get_user_context_string()` already injects facts into the system prompt of EVERY turn (`_chat_logic`). So gender→grammar needs NO hardcoded templates — the fact «Пол: женский» in the prompt + one persona line ("учитывай пол для согласования, адаптируй лексику под род занятий") lets the LLM agree.
- Mobile standalone: `standalone_chat_screen.dart` builds `systemPrompt = agent.skillMd` at the call site → prepend a profile block. Store in a local `ProfileStore` (pattern: `llm_settings_store.dart`).

**Decomposition (2 increments):**
- **Inc 1 — Desktop:** `ProfileStep.tsx` onboarding step (in `onboardingStore` STEP_ORDER, **after `mic-test`** so voice-fill works, before `first-agent`, fully skippable) → `POST /profile` → `save_user_fact` per field. Voice-fill via the existing `/stt` path. Editable later in `Settings`. *(all infra present → fast.)*
- **Inc 2 — Mobile standalone:** `ProfileScreen` + file-backed `ProfileStore` → prepend `_profileBlock(profile)` to the standalone system prompt. Form-only (no local STT on standalone). Editable in mobile settings.

**Anti-pivot ✓** personalization + local data ("Джарвис помнит тебя" = the #1 user-desired feature per the competitive analysis); no cloud profile, no dev-integrations, skippable.

**Tests:** `POST /profile` writes facts + skips empty; `get_user_context_string` contains them; ProfileStep render/skip/save + voice-button-hidden-without-STT; `ProfileStore` round-trip + `_profileBlock` format + standalone chat sends profile+skillMd; grammar = assert the fact is in the prompt (LLM output itself is model-dependent).

---

## B. F5-TTS distillation + sub-1s voice latency

**Goal (Vasily):** improve Russian voice quality AND get first-audio latency **< 1 s**. Three complementary workstreams (NOT one):

1. **Pipeline latency (existing plan — `docs/superpowers/plans/2026-06-03-voice-latency-optimization.md`):** TTFA target cloud < 600 ms / local < 1 s (end-of-speech → first audio). Biggest win = **P1 stream LLM→TTS by sentence** (synth+play each sentence as the LLM keeps generating; client already consumes `voice.tts_chunk`). P0 measure (`scripts/measure_voice_latency.py`), P2 fast streaming TTS, P3 streaming STT. Lands cleanest in the Rust pipeline post-Gate-A.
2. **Engine candidate (existing spike — `docs/superpowers/specs/2026-05-13-omnivoice-eval-spike.md`):** evaluate k2-fsa/OmniVoice (claimed ~40× realtime RTF 0.025, 20 338 h Russian, Apache-2.0) as a faster first-audio path. Decide swap/augment/skip after a 1-day benchmark. Keep F5 as the quality/local path.
3. **NEW — F5 distillation (this item):** distill/fine-tune F5 for (a) better Russian quality and (b) faster inference (fewer NFE steps / smaller student model) to hit the sub-1s first-chunk target on the local GPU path. Complements #1 (pipeline overlap) and #2 (engine choice): distillation attacks the F5 *first-chunk cost* directly. **Needs its own brainstorm+spec** (student architecture, RU corpus, NFE-step reduction / consistency-distillation, quality A/B vs the current F5 checkpoint, RTX training feasibility). Success = local first-audio < 1 s with RU quality ≥ current F5.

**Constraint:** don't sacrifice RU quality; local path stays private (no forced cloud). Anti-pivot ✓ (voice-first is the core moat).

---

## C. Hermes best-practices audit — HAVE vs MISSING

From the 2026-06-10 decision (Hermes-as-foundation REJECTED — anti-pivot; but TAKE the safe infra patterns). Grounded check today:

| Hermes practice | Status | Action |
|---|---|---|
| SKILL.md open standard (agentskills.io) | ✅ HAVE (native: loader/validator/publisher) | — |
| Markdown + SQLite-**FTS** memory (their crown jewel; also OpenHuman "Memory Tree") | ⚠️ **PARTIAL** — `kernel/database.py user_facts` is plain SQLite, **NO FTS5**, **no Markdown/Obsidian-vault export** | **ADD:** FTS5 over facts/conversations for recall; optional Markdown-vault export (browsable, non-tech-friendly — skip Obsidian UI). Ties into [[project-competition]] "Memory Tree steal" + hierarchical summary trees. |
| Telegram gateway = **2-way remote control** ("remote Jarvis") | ⚠️ **PARTIAL** — `agents/telegram` is a **notifier (send-only)**; no inbound command control | **ADD (later, anti-pivot-careful):** a "remote Jarvis" gateway to issue commands / get replies via Telegram. Keep it a life-companion channel, not a dev/VPS terminal. |
| **SAFE self-improve loop** (propose → validate/dry-run → **voice consent**) | ❌ **MISSING** | **ADD (differentiator):** a bounded self-improve loop where the agent proposes a skill/config change, dry-runs it in the sandbox, and asks for **voice consent** before applying. This is the trust-moat version Hermes lacks (they self-improve with no capability bounds). Own brainstorm+spec. |
| Hermes-compatible **catalog source** (curated life-skills) | ❌ **MISSING** — `default_sources()` = user + builtin only (no remote curated source wired) | **ADD:** wire an extra curated catalog source (Hermes/awesome-hermes-compatible), filtered to life-skills, into `default_sources()`. Low effort (catalog already fetches GitHub repos). |
| One-line installer / $5 VPS / terminal UX | N/A — intentionally NOT (that's tech-user turf) | **REJECT** (anti-pivot). |

**Priority order (suggested):** (1) FTS5 memory recall — cheap, high user value ("remembers you"); (2) Hermes catalog source — cheap; (3) SAFE self-improve loop — differentiator, own cycle; (4) Telegram remote-control — larger, later.

---

## Sequencing vs the launch
None of A/B/C blocks the Win+Android public v1 (that's gated on the Armenia entity + EV-cert + Vasily's live-verify — see `2026-06-30-20day-launch-plan.md`). These are **post-v1 / parallel-when-capacity** product-depth items. Pick per Vasily's priority.
