# KALI Community («Сообщество») — marketplace + social, design spec

**Status:** design (2026-06-25). Vision + architecture + phasing for the UGC
catalog of voice-built skills/agents, sharing to social, and a social layer
(likes / ratings / comments). Builds on — does not duplicate —
[`2026-06-19-ugc-share-loop.md`](2026-06-19-ugc-share-loop.md) (the share loop)
and [`../plans/2026-04-13-cloud-catalog.md`](../plans/2026-04-13-cloud-catalog.md)
(the `.kali-agent` package + Supabase catalog client).

**Anti-pivot anchors (binding):** distribution uses the **OS native share
sheet** + `kali://` / https deep links — **never** per-platform OAuth/API.
**On-device / local data is the MOAT** — only *published* skills + their social
metadata go to the cloud; personal agents, conversations, and data stay local.

---

## 1. Goal

> создал агента голосом → опубликовал/поделился → другой человек нашёл его в
> «Сообществе» (или по ссылке/ролику), поставил в один тап, оценил, прокомментировал,
> подписался на автора.

A HuggingFace-style catalog of agents/skills made by ordinary, non-technical
people — the distribution + community flywheel the project's thesis depends on.

## 2. Decisions locked in brainstorm (2026-06-25)

| Decision | Choice |
|---|---|
| Scope | Design the full vision (A + B + C) as one spec, **build in phases**. |
| Identity | **Anonymous device-id** for browse/install/counters; an optional **lightweight KALI account** (handle + magic-link, **not** Google/Apple OAuth) for publish / comment / cross-device attribution. |
| Creator profile | Optional **self-declared** social handles (TikTok/IG/YT/Telegram/site) — free-text the user types, **not** OAuth, no tokens, no platform API. Pure display metadata for "find / follow me". opt-in. |
| Backend | **Supabase** (Postgres + anon-auth + magic-link + RLS + Storage) for UGC catalog + social. GitHub `kali-skills` repo kept for **curated/official** entries. |

## 3. Architecture — three nodes

- **Local (KALI app):** existing `/skills/*` routes + the voice builder + the
  Phase-1 export fix. A **«Сообщество»** surface browses/publishes via a
  `CatalogClient`. Personal data never leaves the device.
- **Cloud (Supabase):**
  - **Auth:** anonymous (device-id) → optional upgrade to a magic-link account.
  - **Postgres:** the catalog + social tables (§4).
  - **Storage:** UGC skill bundles (`.kali-agent` / tar of SKILL.md + skill.yaml
    + manifest).
  - **Row-Level Security (RLS):** public read of `approved` content; a user may
    write only their own ratings/likes/comments; only a skill's creator may edit
    it. RLS is the first line of moderation.
- **GitHub `kali-skills` repo:** the **curated/official** source (trust level),
  surfaced alongside Supabase UGC. Unchanged from today's catalog client.

**Why Supabase + GitHub (hybrid):** social features (likes/ratings/comments,
trending) need a live DB a static git repo can't serve; UGC publishing at scale
can't be PR-per-skill. Supabase covers UGC + social; GitHub stays the vetted,
high-trust shelf.

## 4. Data model (Supabase Postgres)

- `creators` — `id` (auth uid), `handle` (unique display name), `socials`
  (jsonb of self-declared links), `created_at`.
- `skills` — `id`, `slug` (unique), `name`, `description`, `category`,
  `creator_id`, `bundle_path` (Storage), `version`, `template`, `format`
  (skill.yaml | SKILL.md), `status` (`pending`|`approved`|`flagged`|`removed`),
  `install_count`, `created_at`, `updated_at`.
- `ratings` — `skill_id`, `user_id`, `stars` (1–5), unique (skill_id, user_id).
- `likes` — `skill_id`, `device_or_user_id`, unique per id (1 like / device).
- `comments` — `id`, `skill_id`, `user_id`, `body`, `status`, `created_at`.
- `flags` — `id`, `target_type` (`skill`|`comment`), `target_id`, `reason`,
  `reporter_id`, `created_at` (moderation queue).
- `installs` — `skill_id`, `device_id`, `creator_attrib`, `ts` (attribution +
  trending input). Counts only, no PII.

Derived: **trending** = f(installs, likes, ratings, recency) via a SQL view or
edge function.

## 5. The three layers = three phases

### Phase A — P2P share → friend (code-only, NO Supabase) ← unblocks the GAP now
The immediate fix that makes "поделиться с другом" real today, fully anti-pivot,
no infra:
- **Export voice-built agents.** Today `/skills/{name}/export` resolves only
  through `SkillsRegistry` (SKILL.md-indexed), so voice-built skills
  (`manifest.yaml` + `skill.yaml`, written under `agents_dir`) cannot be
  exported at all. Make export find voice-built skills and package them
  (`.kali-agent`: manifest + skill.yaml [+ SKILL.md if present]).
- **Registry reconciliation so an import is LLM-callable.** `install-bundle`
  already registers into the live runtime (core-loop fix 2d), but a skill
  installed under `%APPDATA%/KALI/skills` is withheld from the LLM palette
  because `PluginRegistry._is_callable` looks for `skill.yaml` under `agents_dir`,
  not the install dir. Teach the registry to recognise a skill's actual dir so
  an imported voice agent can be *called*, not just listed.
- **Share/import transport:** native share sheet + `kali://import?b=<base64url
  bundle>` (P2P, no server) or a shared file; optional creator attribution in the
  bundle metadata (handle + self-declared socials).
- **Gates:** none (code-only). **Delivers:** the share→friend loop works offline.

### Phase B — Cloud catalog (Supabase + a domain)
- Provision Supabase (schema §4, Storage, RLS, anon + magic-link auth).
- `CatalogClient` (extend the cloud-catalog plan) talks to Supabase REST.
- **Publish:** app bundles a skill (existing `/skills/publish`) → uploads to
  Storage + inserts a `skills` row (`status=pending`; auto-`approved` when the
  AST safety gate passes + basic heuristics, else held for review) under the
  creator (device-id or account).
- **«Сообщество» browse/search/install** from Supabase `approved` skills + the
  GitHub curated set, with category/trending filters.
- **Creator profile** (handle + opt-in self-declared socials) on the profile and
  on skill cards — "find / follow me".
- **Attribution:** install increments `install_count`; the share artifact + deep
  link carry the creator id.
- **Share-to-reels artifact:** render an agent card (RepaintBoundary→PNG; video
  later) → native share sheet with caption + a catalog deep link
  (`https://<domain>/a/<slug>` or `kali://import?slug=…`) + QR; deferred-install
  landing for an app-less viewer.
- **Gates:** Supabase project, a registered domain for App/Universal Links +
  landing, a content-moderation policy.

### Phase C — Social layer (Supabase)
- **Likes** (1/device), **ratings** (1–5, 1/user), **comments** (account-gated,
  rate-limited).
- **Moderation:** the `status` lifecycle + a **report** button (`flags`) +
  a lightweight review (safe-gate-passing skills auto-approve; flagged content
  is hidden pending review — manual by Vasily at MVP, automatable later). The
  AST safety gate runs on publish **and** install.
- **Trending / leaderboard** from §4 derived signal — "твоего агента поставили
  N раз", top creators.
- **Gates:** moderation operations (review cadence), abuse/rate-limit policy.

## 6. Data flow (publish → discover → install → social → share)

1. **Publish:** bundle (safety gate) → Storage + `skills` row (`pending`/auto-
   `approved`) under creator.
2. **Discover:** «Сообщество» → `CatalogClient.search/trending` → Supabase
   `approved` ∪ GitHub curated.
3. **Install:** download bundle → existing `/skills/install-bundle` (live-runtime
   wired, 2d) → AST safety gate → register → `install_count++`.
4. **Social:** like / rate / comment → Supabase, RLS-guarded.
5. **Share:** card/video → native share sheet + deep link + QR; viewer without
   the app → deferred-install landing → gets *this* agent.

## 7. Anti-pivot preservation (checklist)

- Distribution = native share sheet + `kali://`/https deep links; **no**
  per-platform OAuth anywhere.
- Cloud holds **only** published skills + social metadata + opt-in creator
  profile. Personal agents, conversations, configs, and consent stay **local**.
- The KALI account is KALI's own (handle + magic-link), not a social login;
  self-declared social handles are display strings, never tokens.
- Anonymous-by-default: browse/install/like need no account.

## 8. Testing

- **Phase A:** export round-trip (voice-built skill → bundle → import → present
  in `/agents`) **and** "imported voice skill is LLM-callable" (extends the 2d
  tests); registry-actual-dir resolution unit tests.
- **Phase B:** `CatalogClient` against a mocked Supabase (search/publish/install,
  graceful when unconfigured); publish→Storage→install integration; deep-link
  resolve.
- **Phase C:** RLS policy tests (write-own-only, read-approved-only); the
  moderation lifecycle (flag → hidden → review); trending computation.

## 9. Phasing summary + next step

| Phase | Delivers | Infra/human gate | Code surface |
|---|---|---|---|
| **A** | P2P share→friend works | none | export fix + registry reconciliation (this repo) |
| **B** | cloud catalog, profiles, attribution, share artifact | Supabase + domain | CatalogClient + publish/browse + share/deep-link |
| **C** | likes/ratings/comments + moderation + trending | moderation ops | Supabase tables + social UI + review |

**Each phase gets its own spec → plan → implementation cycle.** This document is
the vision + architecture + phasing; **Phase A gets the first implementation
plan** (it is code-only and unblocks the share GAP). Phases B/C are gated on
Supabase + a domain + a moderation policy and are sequenced after A.

## 10. Open items for the per-phase plans (not decided here)

- Phase A: exact `register_dir`/`_is_callable` change to track a skill's real
  dir without breaking the deliberate "withhold non-skill.yaml skills" guard.
- Phase B: Supabase project region/tier; bundle size limits; the domain (kali.app
  ownership — see prod-readiness audit); auto-approve heuristics.
- Phase C: moderation review cadence + escalation; rate-limit numbers; trending
  weights.
