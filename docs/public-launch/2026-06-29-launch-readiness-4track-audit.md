# KALI — Launch-Readiness Audit, 4 tracks + strategy (2026-06-29)

> Grounded ultracode audit (6 agents) against `main` @ `e3a7369` (UGC voice-reel merged). Verdicts cite real code/tests/configs. Target: public launch ~1 week; Vasily personally testing a rebuilt Windows installer now.

## Per-track readiness

| Track | Verdict | Readiness | Top blockers | External gates |
|---|---|---|---|---|
| **Windows desktop** | config-ready, build-gated | **75%** | No frozen build exists (on-disk installer is stale Jun-25, pre-branch — no reel/PyAV); reel/PyAV unverified in `--onedir`; live two-device loop unproven | EV cert (1–3wk, **long pole**), GPLv3 FFmpeg resolution, CDN for ~4.9GB, owned domain, Privacy/EULA |
| **iOS** | config-ready, build-gated | **60%** | Thin-LAN client (dies at ConnectionScreen w/o desktop); no `.entitlements` → Universal Links dead; WS-4.7 unbuilt | Mac + Apple Dev ($99/yr), owned domain + Team ID for AASA |
| **Android** | config-ready, build-gated | **35%** | Thin-LAN client; mobile sends NO :3006 token (401/loopback-unreachable); WS-4.7 unbuilt; no upload keystore | Google Play ($25), keystore, domain, cloud relay or WS-4.7 |
| **macOS** | config-ready, build-gated | **25%** | No macOS build path at all (CI+fastlane iOS-only); LAN thin client; signing/notarization net-new even with a Mac | Mac build machine, Apple Dev, Developer-ID/notarization, relay or WS-4.7 |

## What genuinely works (verified, not claimed)
- Core voice loop proven by **real-component** tests (`pytest -m core_loop` = **13 passed**): build→deploy→cron→callable→dispatch, schedule→fire→notify, export→import round-trip + honest-fail, voice executes tool_calls on both pipelines, local-provider tool forwarding. Real `SkillExecutor`/`PluginRegistry`, not MagicMock.
- **UGC reel** renders a real MP4 in dev (`tests/reel` = 10, `tests/e2e/test_core_loop_reel_share.py` = 3): `GET /skills/{name}/reel` via real av 17.0.0 + libopenh264 (LGPL-safe) + PIL + qrcode; honest JSON-error envelope + mobile PNG fallback; legible vendored Cyrillic fonts + word-wrap; frame visually verified.
- Security real: M2.1 deny-by-default permission enforcer (72 tests), Rust :3006 loopback-default + per-install 256-bit token (closes the 0.0.0.0 prod-audit blocker), Python host/CORS safe defaults.
- Distribution source shippable-shaped: single-file `DiskSpanning=no`, env-gated signtool subroutine (inert without cert), fail-fast `robocopy /E` staging.

## Strategy alignment — **62%, anti-pivot CLEAN**
Moat axes:
- **Voice creation** — SERVED, strongest, proven not-mocked.
- **UGC share-loop** — SERVED, reel freshly strengthened — **but only the create→share half; the "friend receives" half collapses on mobile.**
- **Mobile** — WEAKEST, make-or-break: **WS-4.7 standalone-lite engine entirely unbuilt**; mobile is a thin LAN remote (~20 dart files, no sqflite/local-LLM/orchestration).
- **Local data** — SERVED on desktop; literally false on mobile/Mac until WS-4.7.

Anti-pivot clean across the board (explicit "NOT OAuth" guards; anon device-id + magic-link; self-declared socials = display strings; marketplace bounded to discovery/trending; zero dev/design integrations; nothing "for show").

**The one deviation to correct:** gated Apple/store tracks (WS-4.1–4.3) were polished though that whole column **cannot ship in a week** (hard-gated on Mac + Apple Dev), while **WS-4.7 — ungated, needs no account/host/hardware, and is the single item that closes the UGC loop on a phone — was deferred.** As built, a desktop-less non-tech friend (the строитель/врач/офисник persona the strategy bets on) cannot *receive* a shared agent. **Correction: stop polishing gated Apple surfaces; either build WS-4.7 so the loop closes standalone, or explicitly scope public-launch v1 as "Windows desktop + desktop-tethered mobile companion" and frame the UGC claim honestly.**

## Critical path to public launch
Long pole = **EV cert (1–3wk org-verification — start NOW)**; everything else parallelizes inside that window.
1. [code-now] Merge reel → main, **full rebuild** (done: merged `e3a7369`; rebuild in progress).
2. [code-now] **Frozen-bundle smoke + two-device live-verify** — boot `kali-backend.exe`, hit `/skills/{name}/reel` once (proves PyAV DLLs + font path post-freeze), then real create→works→share→import on RTX + 2nd device.
3. [code-now, **strategic pick**] WS-4.7 standalone-lite engine **OR** explicit v1 scoping; wire the :3006 pairing token into mobile.
4. [human-gate] GPLv3 FFmpeg resolution (LGPL rebuild / drop torchcodec FFmpeg dep / legal + NOTICE).
5. [account-gate, **start now**] EV cert.
6. [account-gate] Owned domain + CDN (~4.9GB resumable) + legal Privacy/EULA.
7. [hardware/account-gate, post-launch] Apple column — do not let it block v1.

## Right-now (Vasily's personal Windows test)
**Do NOT test the on-disk installer — it's the stale Jun-25 build, contains none of this branch.** After the rebuild, verifiable today (no cert/domain/Mac needed): core voice loop on the RTX machine; **the reel — #1 watch item** (dev-verified, NOT frozen-verified — PyAV native DLLs + font path in `--onedir` are unexercised by tests; first action: boot backend + hit `/skills/{name}/reel`); single-file installer behavior + `.hf_cache` survival; Rust :3006 loopback+token. **Cannot test regardless:** SmartScreen-clean install (no cert); mobile receive-half (WS-4.7 unbuilt); anything iOS/macOS (no Mac).
