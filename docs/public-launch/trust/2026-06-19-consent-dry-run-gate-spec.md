# Consent & Dry-Run Gate — Design Spec (safe-generativity)

> **Status:** DESIGN ONLY. No implementation in this document. This is the plan
> a later agent/session executes. Every code touch-point below was read and
> verified against the current tree (HEAD `1bb735a`); each is cited as
> `file:line`. Where a real value (domain, URL, cert) is not yet chosen, a
> `<PLACEHOLDER>` marker is used rather than an invented value.
>
> **Owner of follow-up:** us-code (kernel + ui) with one us-design copy pass.
> **Audience this protects:** non-tech public users (строитель / врач / таксист)
> who will grant a voice-built or shared agent real access to calendar, email,
> and messages.
>
> **Anti-pivot guardrails honored here:**
> - Consent is **on-device**. No data leaves the machine to authorize an action.
>   This is framed as the MOAT, not a limitation: "решение принимается на твоём
>   устройстве, никто другой его не видит."
> - UGC install/share remains the **OS-native share sheet** (`SharePlus.instance.share`,
>   `mobile/lib/presentation/share_to_reels_screen.dart:100`). Consent does NOT
>   introduce any per-platform OAuth/API. The consent gate fires on the
>   *receiving* device at install/first-run, locally.

---

## 1. Problem statement (verified)

KALI lets non-tech users create agents by voice and install agents shared by
friends. Today an agent reaches **real, autonomous, destructive capability with
a single tap and no plain-language disclosure of what it can touch.** Three
independent gaps compound:

### 1.1 No plain-language consent before real access

- `ui/src/components/VoiceBuilder/PreviewConfirm.tsx:51-69` — the deploy button
  reads «Запустить» and calls `deploy()`. It renders only `SpecCard`; **no
  permissions are shown**.
- `ui/src/components/VoiceBuilder/SpecCard.tsx:37-58` — shows
  template / name / description / config keys (interval, goal, target…). **No
  capability or permission line.**
- `ui/src/components/AgentStore/StoreCards.tsx:46-58` — primary action is
  «Включить» → `onPrimary`; `SetupDialog` (:65-169) asks only for an **API key**,
  never "this agent will read your email."
- `kernel/main.py:1013-1024` — `_approve_agent` sets `user_approved = True` on the
  click; the docstring is explicit: *"Clicking «Включить» … IS the consent."*
  So consent today == "the process is allowed to make its sandbox calls," with
  no statement of scope to the user.

### 1.2 No dry-run / preview before an agent acts

- Grep `dry.?run|simulate|preview_action|подтверд` over `agents/` → **0 files**
  (verified this session).
- `kernel/builder/flow.py:135-173` — `deploy()` runs `generate_skill` then a live
  `deploy_skill`; the only "preview" is the spec card *before* deploy, never a
  preview of an *action's effect*.
- `kernel/builder/deployer.py:49-65` — deploy registers a cron
  (`scheduler.register_cron(...)`) → the agent can fire **autonomously**, with no
  per-fire confirmation.
- `kernel/skill_executor.py:62-84` — `execute()` calls the template directly.
  **No permission or preview hook on the execute path.**

### 1.3 One global boolean grants ALL destructive actions

- `kernel/sandbox/permission_enforcer.py:56-63` — `can_execute` returns `False`
  only if unregistered or `user_approved` is false; for a *known* RPC it checks
  `METHOD_PERMISSIONS`, **but for an unknown method it returns `True`**.
- `kernel/sandbox/permission_enforcer.py:10-17` — `METHOD_PERMISSIONS` lists
  `network.request`, `subscribe_event`, … — **no `execute:*`, no calendar /
  email / messenger entries.**
- `kernel/sandbox/backend.py:139-140` — the action path builds
  `rpc_method = f"execute:{req.action}"`; `kernel/agent_runtime/runtime.py:122`
  passes the bare string `"execute"`. **Neither key exists in
  `METHOD_PERMISSIONS`**, so `can_execute` hits the "unknown method → return
  `True`" branch. Net effect: **once `user_approved` is set, every action —
  `send_email`, `delete_event`, `send_message` — is allowed.** (Verified by
  reading both call sites.)
- `kernel/models.py:9-11` — `VALID_PERMISSIONS` =
  `{storage, notifications, event_bus, network, agents, system}`. **No
  per-capability granularity** (`calendar:read`, `email:send`, …).
- Capability is declared but never gated: `agents/calendar/manifest.yaml:25`
  ships `permissions: []` while exposing `delete_event`
  (`agents/calendar/manifest.yaml:18-21`); `agents/email/manifest.yaml:25-26` and
  `agents/messenger-hub/manifest.yaml:18-19` declare only `network` while exposing
  `send_email` / `send_message`. The rich `capabilities:` block
  (`email.read`, `email.send`, `calendar.write`, `messenger.send`) is **the
  honest source of truth that is currently not surfaced to the user or enforced.**

### 1.4 Consent is not persisted, timestamped, or revocable

- `kernel/models.py:69-70` — `user_approved` + `approval_timestamp` declared.
  Grep over `kernel/` → **`approval_timestamp` is assigned nowhere** (only the
  declaration at `models.py:70`). Verified this session.
- `kernel/main.py:485-492` and `:1023` — `user_approved=True` is set imperatively,
  in-memory only.
- `kernel/main.py:1036-1039` — unload stops the process; **it does not clear
  approval.** There is no revoke surface and no on-disk consent record.

### 1.5 Shared / catalog agents run live with no consent disclosure (UGC path)

- `kernel/skills/installer.py:275-364` — `install_from_bundle` = decode → validate
  (`load_skill`) → AST `_safety_check_scripts` → `_deploy_atomic`. **No consent
  step.** PEP 706 `filter="data"` blocks path traversal/symlinks (:316), which is
  good — but that is a *safety* check, not *consent*.
- `kernel/builder/safety_gate.py:194-205` — docstring states the AST gate
  *"is NOT detected … targets naive/auto-generated code, not adversarial inputs."*
  **By the author's own words it is not a consent substitute.**
- `kernel/skill_executor.py:62-84` — the skill `execute` path **bypasses the
  enforcer entirely** (the enforcer lives on the agent dispatch path in
  `sandbox/backend.py`, not here). So a shared *skill* can act with no permission
  gate at all once loaded.
- Mobile UGC import already POSTs the bundle straight to install:
  `mobile/lib/core/deep_link_service.dart:74-81` → `/skills/install-bundle` with
  `overwrite: true`, showing only `importInstalling` / `importOk` snackbars.
  **The receiving non-tech user sees "Устанавливаю…" then "Готово" — never a
  scope disclosure.**

---

## 2. Design goals & non-goals

**Goals**
1. Before any agent gains real access, the user reads a **plain-language,
   capability-level** statement and explicitly grants it ("Разрешить агенту
   читать календарь?").
2. Before a generative agent performs a **side-effecting** action (send / write /
   delete), the user sees a **dry-run preview** of exactly what will happen and
   confirms — by tap **or by voice**.
3. Consent is **per-capability**, **persisted**, **timestamped**, and
   **revocable**.
4. The shared/UGC install path gets the **same** consent bar as a locally built
   agent, fired locally on the receiving device.
5. Everything works for someone who has never seen a permission dialog —
   wording, defaults, and the voice path are designed for non-tech users.

**Non-goals (explicitly deferred / out of scope)**
- No new networked authorization service. Consent is local. (MOAT.)
- No per-platform OAuth to share or import. (Anti-pivot.)
- Not redesigning the sandbox network proxy, rate limiter, or AST safety gate —
  they stay; we **add a capability dimension and a confirmation step** on top.
- No cryptographic signing of consent records in v1 (local SQLite row is enough;
  signing is a later hardening item — see §8).
- iOS-specific consent UI is out of scope until iOS is in launch scope
  (mobile iOS identity is itself unshippable today — separate gap).

---

## 3. Capability taxonomy (the missing granularity)

The single boolean must become a small, **fixed, human-named** capability set.
Keep it tiny — non-tech users cannot reason about 30 scopes.

| Capability id      | Plain-language (RU)              | Risk  | Example tool (verified)                         |
|--------------------|----------------------------------|-------|-------------------------------------------------|
| `calendar:read`    | «видеть твой календарь»          | low   | `get_events` (`agents/calendar/manifest.yaml:8`)|
| `calendar:write`   | «создавать и удалять события»     | HIGH  | `create_event`/`delete_event` (`:12,:18`)       |
| `email:read`       | «читать твою почту»              | med   | `check_inbox`/`search_emails` (`agents/email/manifest.yaml:9,19`)|
| `email:send`       | «отправлять письма от твоего имени»| HIGH | `send_email` (`agents/email/manifest.yaml:13`)  |
| `messenger:read`   | «читать твои сообщения»          | med   | `read_messages` (`agents/messenger-hub/manifest.yaml:13`)|
| `messenger:send`   | «писать сообщения от твоего имени»| HIGH  | `send_message` (`agents/messenger-hub/manifest.yaml:8`)|
| `network`          | «выходить в интернет»            | med   | existing `network` grant                        |
| `storage`          | «хранить свои данные»            | low   | existing `storage` grant                        |

**Source of truth = the manifest `capabilities:` block, which already exists and
is honest.** The taxonomy is a mapping layer; manifests are not invented anew.

**Risk tiers drive behavior (§5/§6):**
- `low` → granted as part of enabling, shown but not separately gated.
- `med` → shown in the consent card; one grant covers the session.
- `HIGH` (any `*:write`, `*:send`, `delete_*`) → **always requires a dry-run
  confirm per action by default** (see §6), in addition to the install-time
  consent card.

> Implementation note (deferred): a tool→capability map. The cleanest place is a
> small static table keyed by `(agent, tool)` derived from the manifest, consumed
> by both the enforcer and the UI. Do NOT hardcode this in the UI — derive it in
> the kernel and expose it over a route (see §7) so desktop + mobile agree.

---

## 4. Three surfaces, mapped to real code

### Surface A — Install-time consent card ("Разрешить агенту читать календарь?")

Replaces the silent «Запустить» / «Включить» with a disclosure the user reads.

- **Voice-builder deploy:** intercept `PreviewConfirm.tsx:57` (`onClick={() =>
  deploy()}`). Before calling `deploy()`, render a **ConsentCard** listing the
  capabilities the generated spec implies. Keep `SpecCard` (what it does) and add
  the consent block (what it can touch).
- **Store enable:** intercept `StoreCards.tsx:49` (`onClick={() =>
  onPrimary(entry)}`). The card already distinguishes `needs-setup` (key) from
  `idle` (enable). Add a `needs-consent` pre-state that shows the ConsentCard
  before `onPrimary` runs. (The key dialog and the consent card are **separate
  concerns**: key = "make it work," consent = "allow it to act.")
- **Kernel:** `_approve_agent` (`main.py:1013-1024`) must stop being the consent.
  It should set approval **only after** the UI posts an explicit grant carrying
  the capability list (see §7 route). Built-in auto-approve
  (`main.py:485-492`) stays for the 5 built-ins, but those built-ins should also
  carry an explicit, *visible-in-settings* consent record so the model is uniform
  (no "secretly approved" agents).

**Copy (RU, non-tech):**
> «Помощник *Почтальон* сможет: 📥 читать твою почту, ✉️ **отправлять письма от
> твоего имени**. Разрешить?»  → **[ Разрешить ]  [ Не сейчас ]**

HIGH-risk lines are bold + iconned. "Не сейчас" (not "Отмена") keeps the door
open without sounding like an error.

### Surface B — Dry-run preview before a side-effecting action

The new step that does not exist anywhere today (§1.2).

- **Where it hooks:** the action dispatch already funnels through
  `kernel/sandbox/backend.py:139-140` (`execute:{action}`). This is the single
  natural chokepoint to classify an action as side-effecting and, if so, **return
  a `preview` instead of executing**, then require a second confirmed call.
- **Skill path parity:** `kernel/skill_executor.py:62-84` currently bypasses the
  enforcer. Dry-run must also wrap this path (a shared skill that sends a Telegram
  message must preview too). The cleanest design: a thin `ActionGate` the *both*
  paths call, returning either `{"preview": ...}` or executing. Deferred detail,
  but both call sites are named so neither is missed.
- **What a preview contains:** the resolved effect in the user's words — *"Отправлю
  письмо Ивану: «…», тема «…»"* / *"Удалю событие «Стоматолог» 14:00 завтра."*
  The agent must produce this from the same args it would execute with (no second
  LLM call required for built-ins; the args are already structured per the
  manifest tool params).

**Two modes (user-controllable, default = safe):**
- **Default (safe):** every HIGH action previews and waits for confirm.
- **"Доверяю" (per agent, per capability):** after the first confirm the user may
  tick «больше не спрашивать для этого». Stored in the same consent record (§7),
  revocable. Low/med actions never block.

**Copy (RU):**
> «*Секретарь* хочет: 🗓️ удалить событие **«Стоматолог», завтра 14:00**.
> Выполнить?»  → **[ Да, удалить ]  [ Нет ]**  ☐ больше не спрашивать

### Surface C — Voice-consent

Non-tech users build by voice; consent must be answerable by voice without
reaching for the mouse.

- **Reuse the existing parser.** `ui/src/components/VoiceBuilder/voiceCommands.ts`
  already classifies `confirm` / `cancel` with **edge-anchored whole-token
  matching** (`_hasNearEdge`, :35-43) — built precisely to avoid false positives
  like «нетронутый»→«нет». The ConsentCard and Dry-run prompt should consume the
  **same** `parseVoiceCommand` (`:45`) in a `previewing`-like phase, so "да" /
  "разрешаю" / "давай" confirms and "нет" / "не надо" / "отмена" declines.
- **Add a small confirm-word set for consent** (e.g. «разрешаю», «разреши»,
  «можно») alongside the existing `CONFIRM_WORDS` (:2). Keep it short; reuse
  `_hasNearEdge`.
- **Spoken read-back already exists** — `PreviewConfirm.tsx:34-49` speaks the spec
  via `builderApi.say` and only then opens the mic. The same pattern read-backs
  the consent line ("Помощник сможет читать почту и отправлять письма. Разрешить?")
  then listens. **No new audio plumbing needed**; the TTS round-trip semantics are
  already handled (`main.py:1418` blocking playback noted in the component
  comment).
- **Safety rule for voice:** a HIGH-risk action requires an **explicit positive
  token** — silence, ambiguity, or `unknown` intent must **default to "Нет"**,
  never to execute. (Maps to the parser's `{ intent: "unknown" }` fall-through at
  `voiceCommands.ts:66` → treat as decline for HIGH.)

---

## 5. Persisted, revocable consent record

Fixes §1.4 (declared-but-never-written `approval_timestamp`) and §1.5
(no record on the UGC path).

- **Store:** a new table in the existing local SQLite (`kernel/database.py`
  schema, currently `conversations / agent_configs / dashboard_data /
  user_preferences / user_facts` — verified). Add `agent_consents`:
  `(agent_name, capability, granted_at, granted_via {voice|tap}, trust_action
  bool, revoked_at NULLABLE)`. **Local only** — never uploaded (MOAT).
- **Write path:** the grant route (§7) writes the row and *also* sets the
  in-memory `PermissionSet.user_approved` + finally assigns
  `approval_timestamp` (`models.py:70`) so the declared field stops being dead.
- **Read path on startup:** rehydrate approvals from the table so consent
  survives restart (today it is in-memory only, `main.py:491`).
- **Revoke surface:** a settings list "Что разрешено помощникам" with a
  per-capability toggle. Revoke sets `revoked_at`, clears the grant, and — unlike
  today's unload (`main.py:1036-1039`, which leaves approval set) — actually
  removes the capability. Re-enabling re-prompts.

---

## 6. Enforcement changes (make the boolean real)

This is the kernel work that turns the UI promise into a real gate. **Additive**
to the existing enforcer; do not rewrite the sandbox.

1. **Extend `METHOD_PERMISSIONS`** (`permission_enforcer.py:10-17`) so
   `execute:<tool>` maps to the tool's capability (via the tool→capability table,
   §3). This closes the "unknown method → return True" hole
   (`permission_enforcer.py:60-62`) for action dispatch specifically.
2. **Grant set becomes capability-aware.** `VALID_PERMISSIONS`
   (`models.py:9-11`) gains the §3 ids (or a parallel `VALID_CAPABILITIES` set if
   we want to keep the coarse infra perms separate — decide in §9). `PermissionSet`
   already supports named grants + params (`models.py:65-95`), so the structure
   exists; we populate it from the manifest `capabilities:` block instead of the
   thin `permissions:` block.
3. **Classify side-effecting actions** at the chokepoint
   (`sandbox/backend.py:139-140`): if the resolved capability is HIGH and no
   `trust_action` grant exists, **return a `preview` envelope** rather than
   dispatching; require a follow-up confirmed call to execute. Mirror on
   `skill_executor.execute` (`:62-84`).
4. **Keep backward-compat coercion.** `coerce_permissions`
   (`models.py:119-140`) already accepts a flat legacy list and *silently skips
   unknown permissions* (:134-135). Extend it to map legacy bare grants to the new
   ids without breaking existing manifests.

---

## 7. New API surface (named, not built)

All routes are **local** (`127.0.0.1` desktop; LAN `:3006` for the mobile
companion via the Rust backend). No external calls.

- `GET  /agents/{name}/capabilities` → derived capability list + risk tier +
  plain-language strings (single source of truth for desktop + mobile cards).
  *Derives from the manifest; does not invent.*
- `POST /agents/{name}/consent` → body `{capabilities: [...], via: "voice"|"tap",
  trust_actions: [...]}`. Writes the §5 record, sets approval, assigns
  `approval_timestamp`. **Replaces** the implicit consent in `_approve_agent`
  (`main.py:1013-1024`).
- `POST /agents/{name}/consent/revoke` → body `{capability}`. Sets `revoked_at`,
  clears grant.
- `POST /actions/preview` → given `{agent, action, args}` returns the
  plain-language dry-run text (Surface B) **without** side effects.
- `POST /actions/execute` → same payload + `confirmed: true`; only then does the
  side-effecting action run.

> The mobile UGC import (`deep_link_service.dart:74-81`) must call
> `GET …/capabilities` and render a ConsentCard **before** POSTing to
> `/skills/install-bundle` — so a friend installing a shared agent gets the same
> disclosure locally. This is the one change that closes §1.5 on the receiving
> device **without** any platform OAuth (anti-pivot preserved).

---

## 8. UX for a non-tech user (the part that actually matters)

Principles, concrete:

1. **Capability, not jargon.** Never "grant `email:send` scope." Always
   «отправлять письма от твоего имени». The HIGH lines say *"от твоего имени"* —
   that phrase is what makes a таксист pause.
2. **Two buttons, never three.** «Разрешить» / «Не сейчас». No "Advanced."
3. **Bundle the ask.** One card per agent listing all capabilities, not N modal
   dialogs. Cognitive load kills funnels.
4. **Safe default on ambiguity.** Voice `unknown`, timeout, or a closed window =
   **decline**, for HIGH actions specifically. Nothing destructive ever happens
   from silence.
5. **Show it's local.** A one-line reassurance under the card: «Это решение
   остаётся на твоём устройстве.» Turns the consent moment into a trust moment —
   the MOAT, surfaced.
6. **Reversible & visible.** Settings → «Что разрешено помощникам» mirrors every
   grant; revoking is one tap. Users grant more freely when they know they can
   take it back.
7. **Friend-install parity.** The reel-shared agent shows the **same** card on the
   friend's phone before it can act — consistent mental model across create and
   install.

**Funnel caution (honest):** every gate costs activation. Mitigation = (a) gate
HIGH only, never low/med; (b) "Доверяю" after first confirm; (c) bundle into one
card. This keeps the safety win without turning first-run into a checkbox march.

---

## 9. Open decisions for the implementer (do NOT guess)

1. **Capability set scope for v1.** Ship the §3 eight, or start with only the
   three HIGH families (`calendar:write`, `email:send`, `messenger:send`) and a
   read tier? Smaller = faster, less funnel cost.
2. **Separate `VALID_CAPABILITIES` vs. extend `VALID_PERMISSIONS`** — keeping
   infra perms (`storage`, `network`) distinct from user-facing capabilities may
   read cleaner; decide before touching `models.py:9-11`.
3. **Dry-run text generation for *custom* (voice-built) skills.** Built-ins have
   structured args; a generated skill may need a declared "describe-effect" hook
   in `SKILL.md`. Define the contract or scope custom-skill dry-run to v2.
4. **Built-in auto-approve visibility.** Do the 5 built-ins
   (`main.py:485`) appear in the revoke list, or are they pinned? (Recommend:
   visible but pinned, so the model is uniform and honest.)
5. **Voice-consent for HIGH via the LAN companion.** Mobile mic → STT → confirm:
   does the phone confirm locally or relay to desktop? (Recommend: confirm on the
   device that initiated the action.)
6. **Frozen-demo policy.** The investor demo runs on a FROZEN build that does NOT
   contain this gate. Decision: present this as the *next, specced* trust layer
   (it is already promised in the audit handoff
   `.claude/handoffs/2026-06-10-kali2-vision-audit-23fixes-live-test.md`:
   "explicit statuses + 'needs permission: X' + grant button"), not as shipped.

---

## 10. Implementation order (when un-deferred)

Smallest safe slices, each independently shippable:

1. **Taxonomy + read-only `GET /capabilities`** — derive from manifests; surface a
   read-only "this agent can…" line in `SpecCard`/store card. Zero behavior change,
   pure disclosure. (Touches: tool→capability table, `main.py` route,
   `SpecCard.tsx`, `StoreCards.tsx`.)
2. **Persisted consent record + `approval_timestamp`** — `agent_consents` table,
   grant/revoke routes, settings list. Makes consent real & revocable.
   (Touches: `database.py`, `main.py:1013-1024`, new settings view.)
3. **Install-time ConsentCard (Surface A) + voice-consent (Surface C)** — gate
   `deploy()`/`onPrimary` behind the card; reuse `parseVoiceCommand`.
   (Touches: `PreviewConfirm.tsx:57`, `StoreCards.tsx:49`, `voiceCommands.ts`.)
4. **Capability enforcement** — extend `METHOD_PERMISSIONS`; populate grants from
   `capabilities:`; close the "unknown → True" hole for `execute:*`.
   (Touches: `permission_enforcer.py:10-17,56-63`, `models.py:119-140`.)
5. **Dry-run gate (Surface B)** — `ActionGate` on both
   `sandbox/backend.py:139-140` and `skill_executor.py:62-84`; `/actions/preview`
   + `/actions/execute`.
6. **UGC parity** — mobile import calls `GET /capabilities` + ConsentCard before
   `/skills/install-bundle` (`deep_link_service.dart:74-81`).

Slices 1-2 are safe to land even close to launch (disclosure + record, no gating).
Slices 4-5 change behavior and need the manual voice/agent rehearsal before any
build (per the project's plan-first + retest-gate discipline).
