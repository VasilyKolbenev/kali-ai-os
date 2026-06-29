# KALI — Remediation Plan (from the 2026-06-29 4-track audit)

> Derived from [`2026-06-29-launch-readiness-4track-audit.md`](2026-06-29-launch-readiness-4track-audit.md). **Scope decision (Vasily, 2026-06-29): Option C — ship v1 = Windows desktop + desktop-tethered mobile companion NOW; WS-4.7 (mobile standalone-lite) is the first fast-follow (v1.1).** Public launch ~1 week; long pole = EV cert (Vasily starts in parallel).

## v1 definition-of-done (what "shippable" means for Option C)
- Windows desktop: core voice loop + reel verified in the **frozen** bundle on the RTX machine (not just dev).
- Mobile = a **tethered companion**: connects to the user's own desktop over LAN, can drive chat/share, and **actually authenticates to Rust :3006** (today it doesn't → 401/unreachable).
- UGC claim framed **honestly**: "create by voice → share a reel → a friend with KALI installs it" — where "a friend with KALI" means a desktop install (or a tethered phone). The desktop-less-friend standalone path is v1.1 (WS-4.7).
- Public-release legal/signing blockers resolved or consciously accepted (EV cert in flight; GPLv3 FFmpeg resolved).

---

## Phase 1 — v1 code-now remediation (ungated; what we execute now)

Ordered by value to the Option-C v1.

| # | Item | Size | Why (audit) | Verify |
|---|------|------|-------------|--------|
| **P1.1** | **Mobile → Rust :3006 pairing token** | S–M | Audit Android blocker: phone presents NO token → 401 (LAN) or loopback-unreachable. The single thing that makes "tethered companion" actually work. `GET /pairing/token` seam exists; wire it into mobile transport (http + ws) + a pairing UX. | New Rust + Dart tests; manual LAN pair on `kali_test_34` / real phone |
| **P1.2** | **Frozen-bundle live-verify (reel + loop)** | — | Audit #1 risk. **PARTIAL DONE 2026-06-29:** rebuilt `dist_premium/kali-backend` (5.61GB, exit 0) — verified `_internal/` now contains `kernel/reel/assets/*.ttf`, `av.libs/{avcodec-62,avformat-62,swresample-6}.dll`, PIL, qrcode (the audit's "not bundled" finding is now false at the file level). **Remaining:** runtime DLL-load + full reel render + create→works→share on the RTX machine (boot `kali-backend.exe` + hit `GET /skills/{name}/reel`). | Frozen smoke + screenshot of a real rendered reel |
| **P1.3** | **8-agent SSRF: urllib → proxied `self.http_request`** | M | Audit medium: 8 bundled agents (weather/currency/news/github/telegram/todoist/notion/messenger-hub) still egress raw urllib, bypassing the SSRF/whitelist proxy — under-appreciated gap for a UGC-agent launch. Chip `task_52e8b474` (github first — accepts full URL). | Per-agent proxy test; SSRF private-IP block |
| **P1.4** | **GPLv3 FFmpeg resolution** | M + legal | Audit high: 7 FFmpeg DLLs ship GPLv3 (`--enable-gpl`/libx264) with NO license. **DONE 2026-06-29 (Option A — LGPL rebuild):** investigation proved F5 can't drop torchcodec (`torchaudio.load` hard-deps it on torchaudio 2.11), but F5 only DECODES the ref WAV → libx264(GPL encoder) never used → an LGPL FFmpeg build suffices. Swapped `models/ffmpeg/` + `premium_stage/models/ffmpeg/` to **BtbN `n8.1 win64-lgpl-shared`** (identical soname set avcodec-62/…) + bundled `LICENSE.txt`. ABI-verified: `import torchcodec` + `torchaudio.load(ref.wav)` work on the LGPL DLLs (CPU). Reproducible via `scripts/fetch_lgpl_ffmpeg.py --stage`. **Remaining:** full F5 GPU synth on LGPL = part of P1.2 RTX live-verify. | License audit of rebuilt DLLs; F5 still synthesizes |
| **P1.5** | **Honest tethered-UGC framing** | S | **DONE 2026-06-29.** Mobile connection-screen QR hint added (P1.1). Landing deferred-install card now says "Install KALI on your computer and this agent installs itself; the mobile app currently pairs with your KALI desktop" (RU+EN) — steers a desktop-less friend to the desktop (where the agent runs) + frames mobile as companion, so the UGC claim is honest for v1. | Copy review; connection-screen guides pairing |

**Sequencing:** P1.1 first (makes the v1 mobile story real + is a clean code-now win) → P1.3 (security, parallelizable) → P1.4 (legal-touching, start the decision early) → P1.2 when the rebuild is ready → P1.5 alongside.

> Note: the in-flight backend rebuild (`build_backend_premium.py`) is allowed to finish purely as the free P1.2 frozen-reel signal; the full installer (tauri + `.bat`) is NOT being produced until v1 DoD items land (per Vasily — no point building at current readiness).

---

## Phase 2 — fast-follow v1.1 (immediately after v1 ships)

| # | Item | Size | Why |
|---|------|------|-----|
| **P2.1** | **WS-4.7 mobile standalone-lite engine** | XL | The make-or-break: a Dart orchestration spine (chat via cloud LLM, template skills, builder, dashboard, local SQLite, on-device bundle import) so a **desktop-less friend** can receive + run a shared agent — closes the UGC loop standalone. NOT porting ML to phone. **Gets its own brainstorm → spec → writing-plans → subagent-driven cycle** (per the master plan + the 2026-06-19 mobile-standalone design). |

---

## Gated — Vasily's parallel actions (not code-now)
- **EV code-signing cert** — START NOW (1–3wk org-verification = critical path to a SmartScreen-clean public Windows download). Pipeline is inert-ready.
- **Owned domain** — replaces parked `kali.app`; unblocks Universal/App Links + AASA + CDN canonical + updater feed.
- **CDN** for the ~4.9GB single-file installer (resumable/range).
- **Legal-reviewed Privacy Policy / EULA** — drafts have `<PLACEHOLDER>` fields.
- **Mac + Apple Developer** + **Play Console + upload keystore** — the entire Apple/Play column; iOS/macOS are post-v1 regardless. (iOS `associated-domains` entitlements = a small code-now item, but deferred since the whole iOS build is Mac-gated.)

---

## Status
- 2026-06-29: plan authored. Decision C locked. Executing Phase 1 starting with **P1.1 (mobile pairing token)**.
