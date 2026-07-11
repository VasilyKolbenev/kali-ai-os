# Handoff 2026-07-01 — Win+Android prod-readiness MERGED + next-work recorded (anketa · F5 distill · Hermes)

> **HEAD = origin/main = `f30ba00`** — everything PUSHED. No open branch. Model = Fable 5.
> Continues `.claude/handoffs/2026-06-30-ws47-inc2-reminder-runtime-20day-launch-plan.md`.

## ЧИТАЙ В ЭТОМ ПОРЯДКЕ (до кода)
1. **Этот хэндофф**
2. `docs/public-launch/2026-07-01-next-work-plan.md` ← **the forward items** (anketa design / F5 distillation+latency / Hermes have-missing)
3. `docs/public-launch/2026-06-30-win-android-prodready-fix-plan.md` ← what was audited+fixed + the live-test checklist
4. `docs/public-launch/2026-06-30-20day-launch-plan.md` ← launch long poles (Armenia entity, EV-cert)
5. `memory/MEMORY.md` + `memory/project_prodready_audit.md` + `memory/project_launch_plan_20day.md` + `memory/project_competition.md`

## VERIFY STATE
```
git rev-parse --short HEAD                                    # f30ba00 (= origin/main)
.venv\Scripts\python.exe -m pytest -m core_loop -q            # 13 passed
cd mobile && "C:\src\flutter\flutter\bin\flutter.bat" test    # 145 passed (WHOLE tree)
cd src-tauri && cargo check --lib                             # Finished (compiles)
cd ui && pnpm exec vitest run                                 # 142 passed
```
GOTCHA: `tests/kernel/sandbox/test_http_client.py` (11 tests) need **live DNS** (real getaddrinfo on api.example.com, unmocked) — they FAIL in a no-network session, PASS on a networked machine. NOT a code regression (verified pre/post-C12 identical behavior). Worth mocking the resolver later.

## ЗАКРЫТО ЭТУ СЕССИЮ (all on `main`, pushed)
- **Win+Android prod-readiness push — MERGED `a13c840`.** Adversarially-verified 35-finding audit (ultracode `wf_10d426d7-eba`) fully remediated. 46 commits. **All 3 P0** (Android kali://pair dead intent-filter · reminder syncAll race · voice-builder data-loss rmtree) + **all P1** (asyncio GC-cancel tasks · Cyrillic UTF-8 corruption · **GPL x264/x265 prune** copyleft blocker · catalog tar-traversal + checksum-manifest + reject-scripts + bomb-cap + RU-injection needles · **chat no-key → honest RU CTA** vs English dead-end · notification-init device-fire · pair host-allowlist octal/hex bypass · AgentStore crash-safety · cold-start guard · standalone-chat mounted-guards) + **nearly all P2** (DNS-rebinding pin · https-only web-surfer · env control-char guard · honest LLM double-outage · publish safety-gate always-on · EncryptedSharedPreferences · no-token-logging · versionCode+1 / fail-fast release signing · backend-fail honesty Rust-emit + UI red-escalation · webview2 staging · empty-key UX · routines self-heal · field-aware cron · PM-shift). Plan+live-test-checklist: `docs/public-launch/2026-06-30-win-android-prodready-fix-plan.md`.
- **2 documented deferrals:** C12-#3 (bundled agents via `for_agent` for shared rate/audit — needs runtime ctx plumbing; private-IP SSRF block already applies) · C14-f3 (ChatInput component vitest — brittle scaffolding; the no-key fix is backend-tested).
- **Next-work plan recorded `f30ba00`** (`docs/public-launch/2026-07-01-next-work-plan.md`): anketa/profile, F5 distillation, Hermes best-practices audit.

## NEXT WORK (recorded, NOT built — each gets its own brainstorm→spec→plan→TDD)
### A. Profile "анкета" — **DESIGN APPROVED this session, not built**
Optional onboarding questionnaire: имя·пол·род занятий·город·возраст (all skippable) → facts in memory → persona adapts address/**grammar (gender)**/tone/local-context. **Hybrid input** (form + per-field "сказать голосом", voice-button only when STT ready). **Grounding:** desktop `db.save_user_fact()` + `get_user_context_string()` already inject facts into the system prompt every turn (gender→grammar needs NO hardcode); mobile standalone prepends a profile block to `agent.skillMd`. **2 increments:** Inc1 desktop (`ProfileStep.tsx` after mic-test → `POST /profile` → save_user_fact; edit in Settings), Inc2 mobile (`ProfileScreen` + file `ProfileStore` → prepend to standalone system prompt, form-only). Resume with the brainstorming→writing-plans flow (design is done — can go near-straight to spec).
### B. F5 distillation + <1s voice latency (3 complementary workstreams)
(1) pipeline latency `docs/superpowers/plans/2026-06-03-voice-latency-optimization.md` (TTFA <600ms cloud/<1s local; P1 stream LLM→TTS by sentence = biggest win; lands cleanest in Rust post-Gate-A); (2) OmniVoice eval spike `docs/superpowers/specs/2026-05-13-omnivoice-eval-spike.md` (40× RTF candidate); (3) **NEW F5 distillation** — student/fine-tune for RU quality + fewer NFE steps to hit sub-1s local first-chunk; needs own brainstorm+spec (arch, RU corpus, consistency-distillation, RTX training, A/B vs current F5). Don't sacrifice RU quality; local stays private.
### C. Hermes best-practices — HAVE vs MISSING (grounded)
✅ SKILL.md (agentskills.io native). ⚠️ Markdown+SQLite-**FTS** memory PARTIAL (user_facts is plain SQLite, no FTS5, no Markdown-vault) → ADD FTS5 recall (+ optional vault export; ties to the OpenHuman "Memory Tree" steal). ⚠️ Telegram = notifier send-only → ADD 2-way "remote Jarvis" (life-companion, not VPS terminal). ❌ SAFE self-improve loop (propose→dry-run→**voice consent**) MISSING → ADD (trust-moat differentiator). ❌ Hermes-compatible curated catalog source MISSING (`default_sources()`=user+builtin) → ADD (cheap; catalog already fetches GitHub). REJECT one-line-installer/VPS/terminal (anti-pivot). Suggested order: FTS memory → catalog source → self-improve loop → Telegram remote.

## LAUNCH LONG POLES (Vasily, non-code — gate public v1)
🔴 **Armenia legal entity** (day-0; gates EV-cert + Apple Dev + Play Console — NOT RF) · 🔴 **EV-cert** (after entity, 1–3 wk) · domain · CDN · legal. 🟠 **Vasily live-verify** (RTX: frozen reel via libopenh264, confirm **av.libs has NO libx264/libx265** after the GPL-prune, F5 speaks; real Android phone: **reminder fires app-killed+idle**, pair QR, Cyrillic round-trip; skip-key → RU no-key CTA; rename kali-backend.exe → red "ядро не запустилось" banner). Full list in the fix-plan doc.

## ГОТЧИ (verified)
- **BACKGROUND SUBAGENTS ARE UNRELIABLE THIS PERIOD:** repeatedly killed by process restarts (recovered from git — eager per-finding commits saved all impl, lost only read-only reviews), then hard-failed with **"organization has disabled Claude subscription access for Claude Code"**. → Prefer **inline work** (main loop) or verify partials via `git status` after any bg dispatch. Eager per-finding commits are the safety net.
- flutter = `C:\src\flutter\flutter\bin\flutter.bat` (not PATH). **`flutter test test/standalone` OMITS `scheduling/`** — gate with bare `flutter test`.
- ui = pnpm (not npm); venv = uv / `.venv\Scripts\python.exe`; `make` not installed.
- Rust: `cargo check --lib` from `src-tauri`. Tauri 2 event emit needs `use tauri::Emitter`.
- Pre-existing unrelated working-tree drift (`.claude/*`, mobile generated registrants, `ui/tsconfig.tsbuildinfo`, `uv.lock`) — leave; stash the registrant files to `git checkout` between branches.

## ПРИНЦИПЫ (binding)
plan-first + brainstorm HARD-GATE (предложи→обсудим→добавь constraints→сделай) · subagent-driven TDD when subagents work, else inline · verification=evidence (real tests + device-verify) · качество>скорость · anti-pivot (voice creation + mobile + UGC + local data; NO dev-integrations/OS-assistant/crypto/VPS-terminal; token=LAN-security) · русский/кратко · commits on main + ПУШИТЬ · пауза после флоу.

## НАЧНИ С
verify-state + этот хэндофф + `2026-07-01-next-work-plan.md`. Затем спроси Vasily приоритет: **(A) anketa** (design done → straight to spec), **(B) F5 distillation brainstorm**, **(C) Hermes FTS-memory / catalog-source**, или **live-verify support**. Vasily-параллельно: **Armenia entity + EV-cert** (long poles).
