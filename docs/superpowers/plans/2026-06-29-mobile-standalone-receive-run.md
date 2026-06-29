# Mobile Standalone — Receive + Conversational Run (WS-4.7 Increment 1) — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A desktop-less phone can import a shared agent on-device (no server) and have a conversation with it (the agent's SKILL.md as system prompt) via a cloud LLM under the user's own key.

**Architecture:** A new `mobile/lib/standalone/` package with 3 pure-logic units (bundle import, local agent store, cloud-LLM client) + a settings surface for the BYO key + an explicit standalone-mode flag + a deep-link branch + two thin screens. The standalone path fires only when no desktop is paired; the existing tethered (`/skills/install-bundle`, `/chat`, `kali://pair`) paths are untouched.

**Tech Stack:** Flutter/Dart; `archive` (new — tar.gz unpack), `dio` + `flutter_secure_storage` + `path_provider` + `flutter_riverpod` (already deps). Run tests with `C:\src\flutter\flutter\bin\flutter.bat test` (from `mobile/`). Flutter is NOT on PATH.

**Spec:** [`docs/superpowers/specs/2026-06-29-mobile-standalone-receive-run-design.md`](../specs/2026-06-29-mobile-standalone-receive-run-design.md).

**Grounded seams (verified in spec review):**
- Bundle = `base64url(.tar.gz)` of `<name>/SKILL.md` (+ scripts/assets). `package_skill` synthesizes + round-trip-validates a SKILL.md even for voice-built agents (`kernel/skills/publisher.py`), so SKILL.md is ALWAYS present. Export strips `=` padding (`main.py:2487`); restore with `'=' * ((4 - len % 4) % 4)`.
- `deep_link_service.dart:140` `_handleImport`: `ip == null` → bails `importConnectFirst` (line ~150) → this is the standalone insertion point; the `POST /skills/install-bundle` desktop branch is below and stays. `kali://pair` (P1.1) is handled earlier in `_handle`, independent.
- `chat_screen.dart:76` posts to desktop `/chat` keyed on `serverIpProvider` — standalone uses a NEW thin chat screen calling `llm_client` instead, reusing message-bubble widgets.
- Secure-storage pattern to mirror: `mobile/lib/core/token_store.dart` (P1.1) — injectable `TokenKeyValueStore` + `SecureTokenKeyValueStore(FlutterSecureStorage)`.

**Conventions:** idiomatic Dart matching existing files; no hardcoded user-facing strings (use `l10n.dart`); files focused (≤~300 lines); honest failure (never crash). Names are honest-failed to lowercase-latin at export, so a Cyrillic *name* never ships — Cyrillic appears only in description/body.

---

## File Structure
| File | Responsibility |
|------|----------------|
| `mobile/pubspec.yaml` | add `archive` |
| `mobile/lib/standalone/imported_agent.dart` | `ImportedAgent` model (name, description, skillMd, installedAt) + json (de)serialize |
| `mobile/lib/standalone/bundle_importer.dart` | `importBundle(base64url) -> ImportedAgent` (decode→gunzip→untar→SKILL.md→frontmatter), zip-slip safe |
| `mobile/lib/standalone/agent_store.dart` | `AgentStore` interface + `FileAgentStore` (path_provider, one json/agent) |
| `mobile/lib/standalone/llm_client.dart` | `LlmClient` (Anthropic+OpenAI adapters) + `LlmError(kind)`; key from secure storage |
| `mobile/lib/standalone/llm_settings_store.dart` | provider + api-key persistence (secure storage; mirrors token_store) |
| `mobile/lib/core/standalone_mode.dart` | `standaloneModeProvider` (StateProvider<bool>) |
| `mobile/lib/presentation/my_agents_screen.dart` | local "Мои агенты" list → tap → agent chat |
| `mobile/lib/presentation/standalone_chat_screen.dart` | thin chat with an ImportedAgent via llm_client (reuses bubble widgets) |
| `mobile/lib/presentation/llm_settings_screen.dart` | provider + api-key entry |
| `mobile/lib/core/deep_link_service.dart` | extend `_handleImport`: standalone branch when no paired desktop |
| `mobile/lib/presentation/connection_screen.dart` | add «Использовать без компьютера» → set standalone flag |
| `mobile/lib/core/l10n.dart` | new strings (no hardcoded UI text) |
| `mobile/test/standalone/*` | unit + widget tests |

---

## Chunk 1: Core logic (deps + importer + store + llm_client)

### Task 1: Add `archive` dependency
**Files:** Modify `mobile/pubspec.yaml`.
- [ ] **Step 1:** Add `archive: ^4.0.0` (latest stable) under `dependencies`, alphabetically near `dio`.
- [ ] **Step 2:** From `mobile/`: `& 'C:\src\flutter\flutter\bin\flutter.bat' pub get` → expect success.
- [ ] **Step 3:** Verify import resolves: `& 'C:\src\flutter\flutter\bin\flutter.bat' analyze lib` (no new errors). Commit:
```bash
git add mobile/pubspec.yaml mobile/pubspec.lock
git commit -m "build(standalone): add archive dep for on-device bundle unpack"
```

### Task 2: `ImportedAgent` model
**Files:** Create `mobile/lib/standalone/imported_agent.dart`; Test `mobile/test/standalone/imported_agent_test.dart`.
- [ ] **Step 1: Failing test**
```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';

void main() {
  test('round-trips through json', () {
    final a = ImportedAgent(name: 'chef', description: 'повар', skillMd: '# chef\n...', installedAt: DateTime.utc(2026, 6, 29));
    final back = ImportedAgent.fromJson(a.toJson());
    expect(back.name, 'chef');
    expect(back.description, 'повар');
    expect(back.skillMd, '# chef\n...');
    expect(back.installedAt, a.installedAt);
  });
}
```
(Confirm the package import prefix — check an existing test's `package:` name in `mobile/test/`; it may be `kali_mobile` per pubspec `name:`. Use whatever pubspec declares.)
- [ ] **Step 2:** Run → fail (no class).
- [ ] **Step 3: Implement** — a plain immutable class with `toJson()/fromJson()` (name, description, skillMd, `installedAt` as ISO-8601 string). Type hints, doc comment.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat(standalone): ImportedAgent model`.

### Task 3: `bundle_importer.dart`
**Files:** Create `mobile/lib/standalone/bundle_importer.dart`; Test `mobile/test/standalone/bundle_importer_test.dart`.

- [ ] **Step 1: Write failing tests** — build fixtures in-test with `archive` (gzip+tar a `chef/SKILL.md`), base64url-encode (strip `=`), then assert:
```dart
// helper: make a base64url(.tar.gz) payload with the given SKILL.md body under <name>/SKILL.md
String _payload(String name, String skillMd, {List<String> extraPaths = const []}) {
  final archive = Archive();
  final bytes = utf8.encode(skillMd);
  archive.addFile(ArchiveFile('$name/SKILL.md', bytes.length, bytes));
  for (final p in extraPaths) { archive.addFile(ArchiveFile(p, 1, [0])); }
  final tar = TarEncoder().encode(archive);
  final gz = GZipEncoder().encode(tar); // archive v4: returns non-nullable List<int> — NO `!`
  return base64Url.encode(gz).replaceAll('=', ''); // mirror the producer stripping '='
}

test('imports name+description+body from SKILL.md frontmatter', () async {
  final md = '---\nname: chef\ndescription: помощник по рецептам\n---\nТы — повар.';
  final a = await importBundle(_payload('chef', md));
  expect(a.name, 'chef');
  expect(a.description, 'помощник по рецептам');
  expect(a.skillMd.contains('Ты — повар.'), isTrue);
});

test('rejects a zip-slip path', () async {
  final md = '---\nname: chef\ndescription: x\n---\nbody';
  expect(() => importBundle(_payload('chef', md, extraPaths: ['../evil.sh'])), throwsA(isA<BundleImportError>()));
});

test('rejects a bundle with no SKILL.md', () async {
  final archive = Archive()..addFile(ArchiveFile('chef/notes.txt', 3, utf8.encode('abc')));
  final gz = GZipEncoder().encode(TarEncoder().encode(archive)); // v4: non-nullable, no `!`
  expect(() => importBundle(base64Url.encode(gz).replaceAll('=', '')), throwsA(isA<BundleImportError>()));
});

test('restores stripped base64url padding', () async {
  // a payload whose length % 4 != 0 after stripping '=' must still decode
  final md = '---\nname: ab\ndescription: y\n---\nb';
  final a = await importBundle(_payload('ab', md));
  expect(a.name, 'ab');
});
```
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3: Implement**
```dart
import 'dart:convert';
import 'package:archive/archive.dart';
import 'imported_agent.dart';

class BundleImportError implements Exception {
  final String message;
  BundleImportError(this.message);
  @override
  String toString() => 'BundleImportError: $message';
}

/// Decode a `kali://import` `d=` payload (base64url, '='-stripped, of a .tar.gz)
/// into an [ImportedAgent]. Rejects path-traversal entries and a missing/invalid
/// SKILL.md. Pure: no I/O beyond decoding.
Future<ImportedAgent> importBundle(String payload) async {
  final padded = payload + '=' * ((4 - payload.length % 4) % 4);
  final List<int> raw;
  try {
    raw = base64Url.decode(padded);
  } catch (_) {
    throw BundleImportError('payload is not valid base64url');
  }
  final Archive archive;
  try {
    archive = TarDecoder().decodeBytes(GZipDecoder().decodeBytes(raw));
  } catch (_) {
    throw BundleImportError('payload is not a valid .tar.gz');
  }
  for (final f in archive.files) {
    if (f.name.contains('..') || f.name.startsWith('/') || f.name.contains(':')) {
      throw BundleImportError('unsafe path in bundle: ${f.name}');
    }
  }
  final skill = archive.files.firstWhere(
    (f) => f.isFile && (f.name == 'SKILL.md' || f.name.endsWith('/SKILL.md')),
    orElse: () => throw BundleImportError('bundle has no SKILL.md'),
  );
  final md = utf8.decode(skill.content as List<int>);
  final fm = _frontmatter(md);
  final name = fm['name']?.trim();
  if (name == null || name.isEmpty) throw BundleImportError('SKILL.md missing name');
  return ImportedAgent(
    name: name,
    description: (fm['description'] ?? '').trim(),
    skillMd: md,
    installedAt: DateTime.now().toUtc(),
  );
}

/// Parse the leading `---`-delimited YAML frontmatter into a flat string map.
/// Only `key: value` scalars are needed (name, description). Returns {} if none.
Map<String, String> _frontmatter(String md) {
  final lines = md.split('\n');
  if (lines.isEmpty || lines.first.trim() != '---') return {};
  final out = <String, String>{};
  for (var i = 1; i < lines.length; i++) {
    if (lines[i].trim() == '---') break;
    final idx = lines[i].indexOf(':');
    if (idx > 0) {
      final k = lines[i].substring(0, idx).trim();
      var v = lines[i].substring(idx + 1).trim();
      if (v.length >= 2 && ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))) {
        v = v.substring(1, v.length - 1);
      }
      out[k] = v;
    }
  }
  return out;
}
```
> Note `installedAt` uses `DateTime.now()` — keep it out of the equality-sensitive assertions (the test above checks name/description/body, not installedAt for the importer).
- [ ] **Step 4:** Run → pass (4 tests).
- [ ] **Step 5:** Commit `feat(standalone): on-device bundle importer (tar.gz → SKILL.md, zip-slip safe)`.

### Task 4: `agent_store.dart` (file-backed)
**Files:** Create `mobile/lib/standalone/agent_store.dart`; Test `mobile/test/standalone/agent_store_test.dart`.
- [ ] **Step 1: Failing tests** — use a temp dir (inject the base dir so tests don't touch `path_provider` natively):
```dart
test('save -> list -> get -> delete round-trip', () async {
  final dir = await Directory.systemTemp.createTemp('kali_agents_test');
  final store = FileAgentStore(baseDir: dir);
  final a = ImportedAgent(name: 'chef', description: 'повар', skillMd: 'md', installedAt: DateTime.utc(2026,6,29));
  await store.save(a);
  expect((await store.list()).single.name, 'chef');
  expect((await store.get('chef'))!.description, 'повар');
  await store.delete('chef');
  expect(await store.list(), isEmpty);
});
```
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3: Implement** — `abstract class AgentStore` (save/list/get/delete) + `FileAgentStore` writing `<baseDir>/<name>.json`. Constructor takes an optional `Directory baseDir`; when null, lazily resolves `getApplicationDocumentsDirectory()/kali_agents/` (so production needs no arg, tests inject a temp dir → no native `path_provider` call in unit tests). Sanitize `name` for the filename (it's lowercase-latin+hyphen by the export gate, so a simple whitelist check is enough; reject otherwise).
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat(standalone): file-backed AgentStore`.

### Task 5: `llm_settings_store.dart` + `llm_client.dart`
**Files:** Create `mobile/lib/standalone/llm_settings_store.dart`, `mobile/lib/standalone/llm_client.dart`; Test `mobile/test/standalone/llm_client_test.dart`.
- [ ] **Step 1: Failing tests** — inject a fake key store + a mock `Dio` (use `dio`'s `HttpClientAdapter` mock or wrap dio behind a thin sender you can stub). Assert:
```dart
// anthropic: parses content[0].text; openai: parses choices[0].message.content
test('anthropic reply parsed', () async {
  final client = LlmClient(settings: _FakeSettings(LlmProvider.anthropic, 'k'), send: (req) async => {
    'content': [{'type':'text','text':'Привет, я повар.'}]
  });
  final r = await client.chat(systemPrompt: 'Ты повар', history: [ChatMsg.user('привет')]);
  expect(r, 'Привет, я повар.');
});
test('no key throws LlmError.noKey', () async {
  final client = LlmClient(settings: _FakeSettings(LlmProvider.anthropic, null), send: (_) async => {});
  expect(() => client.chat(systemPrompt: 's', history: []), throwsA(predicate((e) => e is LlmError && e.kind == LlmErrorKind.noKey)));
});
```
(Design `LlmClient` to take an injectable `send` function `Future<Map> Function(LlmRequest)` so tests never hit the network; the production `send` uses `dio`.)
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3: Implement**
  - `llm_settings_store.dart`: mirror `token_store.dart` — `LlmSettingsStore` over an injectable key/value (secure storage in prod) with `provider`/`apiKey` get/set.
  - `llm_client.dart`: `enum LlmProvider {anthropic, openai}`, `enum LlmErrorKind {noKey, network, apiError, quota}`, `class LlmError`, `class ChatMsg {role, content}`. **`LlmClient.settings` MUST be an injectable abstraction** (e.g. an `LlmSettings` interface exposing `provider`/`apiKey`), NOT the concrete secure-storage store — so the test's `_FakeSettings` never touches the native keychain. `LlmClient.chat`: if no key → `LlmError(noKey)`; build the per-provider request (Anthropic `POST https://api.anthropic.com/v1/messages`, headers `x-api-key` + `anthropic-version: 2023-06-01`, body `{model, max_tokens, system: systemPrompt, messages}`; OpenAI `POST https://api.openai.com/v1/chat/completions`, header `Authorization: Bearer`, body `{model, messages:[{role:'system',...}, ...history]}`); call `send`; map non-2xx/`DioException` → `LlmError(network|apiError|quota)`; parse the provider reply. **Grounding item:** use the same default model ids the desktop router uses (check `kernel/llm_router.py` / `config/kali.yaml` `llm.cloud_model`) so mobile defaults match; keep them in per-provider constants.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat(standalone): cloud LLM client (anthropic+openai, BYO key) + settings store`.

---

## Chunk 2: Integration (mode flag + deep-link + settings UI + screens)

### Task 6: `standaloneModeProvider` + connection-screen entry
**Files:** Create `mobile/lib/core/standalone_mode.dart`; Modify `mobile/lib/presentation/connection_screen.dart`, `mobile/lib/core/l10n.dart`; Test `mobile/test/standalone/standalone_mode_test.dart`.
- [ ] **Step 1:** Test that toggling `standaloneModeProvider` (a `StateProvider<bool>`, default false) flips state; widget test that tapping the new «Использовать без компьютера» button sets it true and navigates to MainScreen.
- [ ] **Step 2:** fail.
- [ ] **Step 3:** Add `standaloneModeProvider`. Add an l10n key `useWithoutComputer` (ru/en/es/zh/de). On `connection_screen.dart`, add a secondary `TextButton` below the connect action that sets `standaloneModeProvider` true and routes to MainScreen (mirror the connect-success navigation). Keep manual IP + QR pairing intact.
- [ ] **Step 4:** pass. **Step 5:** Commit `feat(standalone): explicit standalone-mode flag + connection-screen entry`.

### Task 7: Deep-link standalone import
**Files:** Modify `mobile/lib/core/deep_link_service.dart`, `mobile/lib/core/l10n.dart`; Test `mobile/test/standalone/deep_link_standalone_test.dart`.
- [ ] **Step 1: Failing test** — extract the import decision into a testable seam: a function that, given `(hasPairedDesktop, payload)`, either calls the on-device importer+store (standalone) or returns "use server". Assert: no paired desktop → `bundle_importer` + `agent_store.save` invoked, server NOT called; paired desktop → server path chosen. (Use fakes for store + a flag for the server call.)
- [ ] **Step 2:** fail.
- [ ] **Step 3:** In `_handleImport`, at the current `ip == null` bail point: if `standaloneModeProvider` is true OR no desktop is paired, import on-device (`importBundle` → `agentStore.save`), show an l10n success snackbar, route to "Мои агенты"; on `BundleImportError`, show an honest error snackbar (l10n). Leave the `POST /skills/install-bundle` branch (desktop paired) exactly as-is. Add l10n key `importedStandalone`; **reuse the EXISTING `importFailed` key** (already used at `deep_link_service.dart:172` — do NOT redefine it).
- [ ] **Step 4:** pass. **Step 5:** Commit `feat(standalone): kali://import installs on-device when no desktop paired`.

### Task 8: LLM settings screen
**Files:** Create `mobile/lib/presentation/llm_settings_screen.dart`; Modify `mobile/lib/core/l10n.dart`; Test `mobile/test/standalone/llm_settings_screen_test.dart`.
- [ ] **Step 1:** Widget test: entering a key + choosing a provider persists via a fake `LlmSettingsStore`.
- [ ] **Step 2:** fail.
- [ ] **Step 3:** A simple screen: provider dropdown (Anthropic/OpenAI) + obscured api-key `TextField` + save. Persists via `LlmSettingsStore`. l10n for labels + the "why we need this" helper ("ключ к твоей AI-модели; хранится только на телефоне"). Reachable from settings + from the no-key chat prompt.
- [ ] **Step 4:** pass. **Step 5:** Commit `feat(standalone): LLM provider + API-key settings`.

### Task 9: "Мои агенты" + standalone chat screen
**Files:** Create `mobile/lib/presentation/my_agents_screen.dart`, `mobile/lib/presentation/standalone_chat_screen.dart`; Modify nav + `mobile/lib/core/l10n.dart`; Test `mobile/test/standalone/my_agents_screen_test.dart`, `mobile/test/standalone/standalone_chat_test.dart`.
- [ ] **Step 1: Failing widget tests** — `my_agents_screen` lists agents from a fake `AgentStore` (empty-state + populated); `standalone_chat_screen` with a fake `LlmClient` returning a canned reply shows the reply; no-key (`LlmError.noKey`) shows the "add your AI key" prompt routing to settings.
- [ ] **Step 2:** fail.
- [ ] **Step 3:** 
  - `my_agents_screen.dart`: lists `agentStore.list()` (name + description), honest empty-state ("пока нет агентов — поделись ссылкой с другом или импортируй"), tap → `standalone_chat_screen`.
  - **REQUIRED extraction sub-step:** `chat_screen.dart` has NO reusable bubble widget — the bubble is built inline in the `ListView.builder` itemBuilder (~lines 153-197) and the `ChatMessage` model is defined inline (~line 10). First extract a shared `MessageBubble` widget → NEW `mobile/lib/presentation/widgets/message_bubble.dart` (and move/ share `ChatMessage` to a shared location), then have BOTH `chat_screen.dart` and the new standalone screen use it. (This is required work, not optional — reflect it in the file list + commit.)
  - `standalone_chat_screen.dart`: a thin chat using the extracted `MessageBubble`. Sends `systemPrompt = agent.skillMd` + history to `LlmClient.chat`; renders the reply; on `LlmError` renders the matching honest message (noKey → CTA to settings; network/apiError/quota → inline error). Reachable in standalone mode from MainScreen.
  - Wire `my_agents_screen` into the standalone-mode navigation (so standalone MainScreen surfaces it).
- [ ] **Step 4:** pass. **Step 5:** Commit `feat(standalone): Мои агенты list + standalone agent chat`.

---

## Final verification
- [ ] `& 'C:\src\flutter\flutter\bin\flutter.bat' test` (from `mobile/`) → all standalone tests green + no regressions in existing tests (token_store, pair_link, share_to_reels).
- [ ] `& 'C:\src\flutter\flutter\bin\flutter.bat' analyze` → no new issues.
- [ ] Note in the handoff: **live-verify deferred** — real phone (`kali_test_34`, not `Pixel_7`), standalone mode (no desktop), tap a real `kali://import` → agent appears in «Мои агенты» → set a real LLM key → chat → in-character reply.

## Out of scope (later increments — do NOT build here)
Tool execution / Dart template runtime (reminder/tracker scheduling) · build-by-voice on phone · dashboard · cloud catalog · deferred-link landing · Pro voice · SQLite migration.
