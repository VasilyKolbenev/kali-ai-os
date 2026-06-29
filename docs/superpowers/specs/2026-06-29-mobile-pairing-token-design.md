# KALI — Mobile ↔ Desktop Pairing Token (P1.1) — Design Spec

**Date:** 2026-06-29
**Status:** Design — locked decision, pending execution
**Source:** Remediation plan P1.1 ([`docs/public-launch/2026-06-29-remediation-plan.md`](../../public-launch/2026-06-29-remediation-plan.md)); audit Android blocker (phone presents no :3006 token → 401/unreachable). Scope: makes the **Option-C tethered mobile companion** actually authenticate to the desktop over LAN.

## 1. Problem
The Rust control plane (:3006) enforces a per-install 256-bit token on every non-loopback (LAN) request (`Bearer` or `X-KALI-Token`; loopback exempt; bind LAN only when `KALI_LAN=1`). The Flutter mobile app has **zero** token handling → on a real phone over LAN it gets 401 (token mode) or can't reach a loopback-bound desktop at all. The tethered-companion story is broken until the phone (a) obtains the token, (b) persists it, (c) presents it on every HTTP **and** WebSocket call.

## 2. Locked design — QR deep-link pairing (native camera)
Chosen for the best non-tech UX with **zero new mobile dependencies** (reuses the registered `kali://` scheme + existing deep-link handler; no in-app scanner):

1. **Desktop (Tauri React UI)** shows a **"Pair phone"** view: fetches `GET /pairing/token` (loopback-only, returns `{token, path}`), determines the desktop LAN IP, ensures the backend is LAN-bound, and renders a **QR encoding `kali://pair?ip=<lan-ip>&token=<token>`**. The `ip` param is a **bare host (no port)** — the mobile side appends `:3006` itself (`ServerConfig.port`), so encoding a port here would double it. (Implemented: `/pairing/lan-ip` also reports `lan_enabled`; the view shows an honest "set `KALI_LAN=1` and restart" prompt when LAN bind is off — the backend binds at startup only, no runtime rebind.)
2. **User points the phone's native camera** at the QR → the OS offers to open the `kali://` link in KALI (the scheme is already registered on Android `host` + iOS `CFBundleURLSchemes`).
3. **Mobile deep-link handler** gains a `pair` route: extracts `ip` + `token`, stores them (`flutter_secure_storage`), sets `serverIpProvider`, and connects.
4. **Every mobile HTTP call** carries `X-KALI-Token: <token>` via a Dio interceptor.
5. **WebSocket** (Dart `web_socket_channel` can't send headers) carries the token as a **query param** `ws://<ip>:3006/ws?token=<token>`; the Rust `/ws` route is extended to accept the token from the query string for the upgrade.

**Anti-pivot check ✓:** the token is **local LAN security** (per-install secret pairing the user's own two devices) — NOT a cloud account, NOT OAuth, NOT identity. On-thesis for the tethered v1; no external dependency.

## 3. Grounded seams (verified)
**Rust (DONE, extend only):**
- Token: `%APPDATA%/KALI/control-plane-token` (64-hex, CSPRNG), `KALI_TOKEN_FILE` override — `src-tauri/src/backend/auth.rs:75-146`.
- Middleware `require_token` accepts `Authorization: Bearer` + `X-KALI-Token` (case-insensitive, trimmed), loopback-exempt, 401 on fail — `auth.rs:164-249`. Public allowlist: `/health`, `/version`.
- `GET /pairing/token` EXISTS, loopback-only, returns `{token, path}`, 404 to non-loopback — `auth.rs:259-294`.
- Bind: default `127.0.0.1:3006`; LAN via `KALI_LAN=1`; precedence `KALI_RUST_BIND` > `KALI_LAN` > loopback — `src-tauri/src/backend/mod.rs:32-60`.
- **Extension needed:** the `/ws` upgrade route must accept `?token=` (Dart ws can't send headers). Add query-token acceptance to the ws route's auth path only (keep header auth for HTTP).

**Mobile (build):**
- `mobile/lib/core/http_client.dart` — `dioProvider` is a bare `Dio(BaseOptions(...timeouts))`, **no interceptor** → add a token-injecting `InterceptorsWrapper`.
- `mobile/lib/core/websocket_client.dart` — `connect(ip)` opens `ws://$ip:3006/ws` → append `?token=`.
- `mobile/lib/core/config.dart` — `serverIpProvider` (in-memory only); **no token storage, no `flutter_secure_storage`/`shared_preferences`** → add `flutter_secure_storage`.
- `mobile/lib/core/deep_link_service.dart` — existing `kali://import` handler → add a `pair` route.
- `mobile/lib/presentation/connection_screen.dart` — manual IP entry → add "Отсканируй QR на десктопе" guidance + keep manual entry as fallback.

**Desktop UI (build):** a pairing view under `ui/` that calls `/pairing/token`, gets the LAN IP, ensures LAN bind, renders the `kali://pair` QR.

## 4. Non-goals (YAGNI)
- No in-app QR scanner (native camera handles it).
- No cloud account / OAuth / remote pairing (LAN-local only).
- No token rotation UI (regenerate = delete the token file; out of scope for v1).
- Not changing the existing `kali://import` agent-share flow.

## 5. Error handling
- Missing/expired token on the phone → HTTP 401 / ws close → mobile surfaces "повторно отсканируй QR для подключения" and routes back to the pairing/connection screen (never a silent hang).
- `/pairing/token` only reachable on the desktop itself (loopback) — the phone NEVER calls it directly; it only receives the token via the scanned deep-link.
- LAN not enabled → desktop pairing view enables `KALI_LAN` (or instructs) before showing the QR; if the phone can't reach the IP, connection screen shows a clear network-hint.

## 6. Testing
- **Rust:** unit test the `/ws` route accepts a valid `?token=` and rejects a bad/missing one from a non-loopback peer (mirror existing `auth.rs` tests).
- **Mobile:** unit-test the Dio interceptor injects `X-KALI-Token` when a token is stored (and omits it when not); test the `kali://pair?ip=&token=` deep-link parser extracts + persists both; test the ws URL builder appends `?token=`. (`flutter test`; mirror `share_to_reels_test.dart` style.)
- **Live (deferred to RTX two-device pass):** desktop shows QR → real phone native-camera scan → opens KALI → pairs → authenticated chat over LAN.

## 7. Open grounding items for the implementer (ground first)
- Exact Rust `/ws` route registration + how to thread `?token=` through its auth (the HTTP `require_token` middleware vs the ws upgrade handler).
- How the desktop UI triggers/【ensures LAN bind (`KALI_LAN`) at pairing time — runtime toggle vs documented restart.
- The desktop LAN-IP discovery method (Tauri/Rust side).
