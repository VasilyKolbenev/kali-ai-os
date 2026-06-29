# KALI — Mobile Standalone: Receive + Conversational Run (WS-4.7 Increment 1) — Design Spec

**Date:** 2026-06-29
**Status:** Design — approved scope, pending spec review + writing-plans
**Source:** Phase 2 of the remediation plan ([`docs/public-launch/2026-06-29-remediation-plan.md`](../../public-launch/2026-06-29-remediation-plan.md)). Architecture decision = Option B (on-device lite engine) per [`docs/public-launch/2026-06-19-mobile-standalone-design.md`](../../public-launch/2026-06-19-mobile-standalone-design.md). This spec is **Increment 1** of that — the smallest viable slice that closes the make-or-break UGC "receive" half (audit `2026-06-29-launch-readiness-4track-audit.md`: a desktop-less friend currently cannot RECEIVE a shared agent).

## 1. Problem & decision
The Flutter app is a thin LAN client; a friend without a desktop installs nothing when they tap a shared `kali://import` link (`deep_link_service.dart:140` bails with `importConnectFirst` when no backend IP). The 2026-06-19 design chose **Option B** (on-device lite engine, no ML port — cloud LLM/voice under the user's key). Increment 1 delivers the **receive + conversational run** slice: import a shared agent **on-device** and **talk to it** via a cloud LLM, with the agent's SKILL.md as the system prompt. No tool execution, no template scheduling, no build-by-voice (later increments).

## 2. Scope / non-goals
### In scope
- On-device import of a `kali://import?n=&d=<base64url(.tar.gz)>` bundle (decode → unpack → parse SKILL.md → store locally), with zip-slip protection.
- A local "Мои агенты" registry (file-backed) — list/get/delete imported agents.
- Conversational run: chat with an imported agent — its SKILL.md body becomes the system prompt; a cloud LLM (user's own key) replies in character.
- BYO LLM key + provider selection in mobile settings.
- A "use without a computer" entry so the app no longer dead-ends at the connection screen.

### Non-goals (YAGNI — later increments)
- Tool execution / dispatch; the Dart template-skill runtime (reminder/tracker/notifier scheduling).
- Build-an-agent-by-voice on the phone.
- Dashboard, full agent management, cloud catalog ("Сообщество"), deferred-link landing, Pro cloud voice.
- SQLite (a file-backed store suffices for a simple agent list; revisit when chat-history/scheduling state arrives).
- Changing the existing tethered (desktop-paired) path or the `kali://import` server path — standalone is a parallel mode used only when there is no paired desktop.

## 3. Architecture & components (`mobile/lib/standalone/`)
Each unit is independently testable; keep files focused (≤~300 lines).

### 3.1 `bundle_importer.dart`
```dart
class ImportedAgent { final String name, description, skillMd; }
/// Decode + unpack a kali://import payload into an ImportedAgent.
/// base64url-decode (restore padding) → gunzip+untar (`archive`) → locate
/// SKILL.md → parse YAML frontmatter (name, description) + body. Rejects
/// path-traversal entries (zip-slip) and a missing/invalid SKILL.md.
Future<ImportedAgent> importBundle(String base64urlPayload);
```
Mirrors the receive side of `kernel/skills/installer.py` / `publisher.package_skill` (which synthesizes a SKILL.md for voice-built agents, so the bundle always carries one). **Grounding item:** confirm the exact tar layout + that SKILL.md is always present by inspecting `kernel/skills/publisher.py` (`package_skill`) / `kernel/catalog/package.py` and a real produced bundle.

### 3.2 `agent_store.dart`
```dart
abstract class AgentStore {
  Future<void> save(ImportedAgent a);
  Future<List<ImportedAgent>> list();
  Future<ImportedAgent?> get(String name);
  Future<void> delete(String name);
}
/// File-backed implementation: one JSON file per agent under
/// getApplicationDocumentsDirectory()/kali_agents/. No new native dep
/// (path_provider is already present). Interface lets a later increment swap
/// to sqflite without touching callers.
```

### 3.3 `llm_client.dart`
```dart
enum LlmProvider { anthropic, openai }
/// Distinct failure variants so the chat surface renders each honestly
/// (maps 1:1 to the §5 error table).
enum LlmErrorKind { noKey, network, apiError, quota }
class LlmError implements Exception { final LlmErrorKind kind; final String message; }
class LlmClient {
  /// Single non-streaming chat completion. systemPrompt = the agent's SKILL.md
  /// body; history = prior turns. Uses dio (already a dep) + the user's key
  /// from secure storage. Throws LlmError(kind) — callers surface it honestly,
  /// never crash.
  Future<String> chat({required String systemPrompt, required List<ChatMsg> history});
}
```
Start with **Anthropic + OpenAI** (both simple REST; Anthropic = `POST /v1/messages`, OpenAI = `POST /v1/chat/completions`). Key + provider stored via `flutter_secure_storage` (reuse the `TokenStore` pattern from P1.1).

### 3.4 Settings — LLM key/provider
A settings surface to choose `LlmProvider` + paste the API key (stored in secure storage). The only standalone-consistent source of a key (no desktop to sync from). If unset, chat shows an honest "add your AI key" prompt that routes here.

### 3.5 Deep-link standalone import (`deep_link_service.dart`)
Extend `_handleImport`: when there is **no paired/connected desktop** (the case that currently bails with `importConnectFirst`), import **on-device** via `bundle_importer` → `agent_store`, then route to "Мои агенты". When a desktop IS paired, keep the existing `/skills/install-bundle` server path unchanged. (The `kali://pair` path from P1.1 is untouched.)

### 3.6 UX
- **Connection screen** gains a secondary action **«Использовать без компьютера»** → sets an **explicit `standaloneModeProvider` (bool)** → MainScreen in standalone mode (no IP required). Manual IP entry + QR pairing remain for tethered. (Use an explicit flag, NOT `serverIpProvider == null` — a paired-but-disconnected desktop also has transient null IP, so inferring would misroute.)
- **«Мои агенты»** screen: lists `agent_store.list()`; tap → agent chat.
- **Agent chat screen** (NEW, thin): a dedicated standalone agent-chat screen that **reuses the existing message-bubble presentation widgets** but calls `llm_client` (not the desktop `/chat`) with `systemPrompt = agent.skillMd` + history. Preferred over threading a mode flag through `chat_screen.dart` (which hardwires `serverIpProvider`/`/chat`/its own `Dio`).

### 3.7 New dependency
`archive` (tar.gz unpack). `dio`, `flutter_secure_storage`, `path_provider`, `flutter_riverpod` already present. No sqflite in this increment.

## 4. Data flow
```
friend taps kali://import?n=&d=  → (no paired desktop → standalone)
  → bundle_importer.importBundle(d)  → ImportedAgent{name, description, skillMd}
  → agent_store.save(...)            → "Мои агенты" lists it
  → tap agent → agent chat → llm_client.chat(systemPrompt=skillMd, history)
              → cloud LLM (user's key) → in-character reply
```

## 5. Error handling (honest, never crash)
| Failure | Behavior |
|---|---|
| No LLM key set | Chat shows "добавь свой AI-ключ в настройках" → routes to settings. |
| Malformed / non-base64url bundle | Import fails with a clear error toast; nothing stored. |
| zip-slip / missing-or-invalid SKILL.md | Import rejected; honest error. |
| LLM network / API error / no quota | Error message in the chat thread; agent + history preserved. |
| Desktop IS paired | Standalone path not taken — existing tethered `/skills/install-bundle` + `/chat` used. |

## 6. Anti-pivot ✓
Imported agents + chat live **only on the phone** (file store in the app sandbox). The only egress is the LLM prompt to the user's chosen provider under the user's own key — honestly disclosable ("your assistant talks to the AI model you chose"). Zero KALI server, zero OAuth, native-share + `kali://` untouched. Makes "your data stays on your phone" literally true — strengthens the moat (per the 2026-06-19 design's core rationale).

## 7. Testing (`flutter test` via `C:\src\flutter\flutter\bin\flutter.bat`)
- `bundle_importer`: unpack a fixture bundle → correct name/description/skillMd; reject a zip-slip entry; reject a bundle with no SKILL.md; handle a **Cyrillic description with a latin name** (names are honest-failed to lowercase-latin at export — `main.py:2471` — so a Cyrillic *name* never ships; the Cyrillic content that DOES ship is in the description/body).
- `agent_store`: save→list→get→delete round-trip against a temp dir.
- `llm_client`: mock dio → parses an Anthropic reply + an OpenAI reply; no-key → throws `LlmError` (honest); network error → `LlmError`.
- Deep-link: a `kali://import` with no paired desktop → `bundle_importer` + `agent_store.save` invoked (standalone), NOT the server POST; with a paired desktop → server path unchanged.
- Widget: "Мои агенты" lists stored agents; agent chat with a mock `llm_client` shows the reply; no-key state shows the settings prompt.
- **Live (deferred):** real phone (`kali_test_34`) — tap a real shared `kali://import` with the app standalone (no desktop) → agent appears → chat with a real key → in-character reply.

## 8. Open grounding items for the implementer
- Exact bundle tar layout (`<name>/SKILL.md`) — confirmed in review via `kernel/skills/publisher.py` `package_skill` + `_synthesize_skill_md` (synthesizes + round-trip-validates a SKILL.md for voice-built agents, so one is always present); export emits `base64url(...).rstrip("=")` (`main.py:2487`), so restore padding with `"=" * (-len % 4)`. The live `kali://import` carrier uses the `.tar.gz` (publisher) path, NOT the `.kali-agent` zip — target the tar.gz.
- Anthropic/OpenAI request/response shapes (system-prompt placement, max_tokens) — keep a thin per-provider adapter inside `llm_client`.
- (Resolved in §3.6: dedicated thin standalone chat screen reusing message-bubble widgets; explicit `standaloneModeProvider` bool, not inferred from null.)
