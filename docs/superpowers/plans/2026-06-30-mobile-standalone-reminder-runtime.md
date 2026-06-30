# Mobile Standalone Reminder Runtime (WS-4.7 Increment 2) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reminder agent received on a desktop-less phone actually fires local notifications on its schedule (window + interval), with no desktop, no server, and no LLM in the execution loop.

**Architecture:** Pre-scheduled local notifications + app-open top-up. Pure Dart computes fire times from the (real, nested) voice-built `skill.yaml` config; a thin gateway over `flutter_local_notifications` + `timezone` registers them; a scheduler service syncs all enabled reminder agents on import / app-resume / toggle / snooze. UI gives a toggle + next-fire + snooze. Honest about OS background limits.

**Tech Stack:** Flutter (package `kali_mobile`), `flutter_riverpod`, new deps `flutter_local_notifications` + `timezone` + `yaml`. Tests via `C:\src\flutter\flutter\bin\flutter.bat test` (flutter is NOT on PATH).

**Spec:** [`docs/superpowers/specs/2026-06-30-mobile-standalone-reminder-runtime-design.md`](../specs/2026-06-30-mobile-standalone-reminder-runtime-design.md)

**Binding conventions:** TDD (test first, watch it fail, minimal impl, watch it pass, commit). Commit after every task. русский/кратко in user-facing strings. Never `print()`. Pure functions get an injected clock (`from`), never `DateTime.now()`. All commits on `main`, pushed at the end of the flow.

**Run commands (Windows / Git-Bash):**
- One test file: `cd mobile && "C:/src/flutter/flutter/bin/flutter.bat" test test/standalone/<file>.dart`
- Full mobile suite: `cd mobile && "C:/src/flutter/flutter/bin/flutter.bat" test`
- Add a dep: `cd mobile && "C:/src/flutter/flutter/bin/flutter.bat" pub add <pkg>`

---

## File Structure

**New (`mobile/lib/standalone/scheduling/`):**
- `ru_interval_parse.dart` — pure ports of `_parse_interval_hours` / `_parse_interval_minutes` + a best-effort `time_window` parser.
- `reminder_config.dart` — `ReminderConfig` + `parseReminderConfig(map, fallbackMessage:)`.
- `reminder_schedule.dart` — pure `nextFireTimes(...)`.
- `notification_ids.dart` — pure id-block math (testable without native).
- `notification_gateway.dart` — `NotificationGateway` interface + `LocalNotificationGateway` (native impl).
- `reminder_scheduler.dart` — `ReminderScheduler` (syncAll / setEnabled / snooze) + the global-budget rule.

**Modified (Increment-1 units — surgical):**
- `mobile/lib/standalone/imported_agent.dart` — add `template` / `config` / `enabled` / `snoozeUntil` + `copyWith`.
- `mobile/lib/standalone/bundle_importer.dart` — also extract `skill.yaml` (`yaml` dep) → `template` + `config`.
- `mobile/lib/core/deep_link_service.dart` — after `importOnDevice`, trigger `scheduler.syncAll`.
- `mobile/lib/presentation/my_agents_screen.dart` — reminder row (toggle + next-fire + snooze), permission-denied state; `reminderSchedulerProvider` / `notificationGatewayProvider`.
- `mobile/lib/presentation/main_screen.dart` (or app root) — `WidgetsBindingObserver` → `scheduler.syncAll` on resume.
- Native config: `mobile/android/app/src/main/AndroidManifest.xml`, `mobile/ios/Runner/AppDelegate.swift`, `mobile/ios/Runner/Info.plist`.

**New tests (`mobile/test/standalone/scheduling/`):** one per pure unit + the scheduler (fake gateway); widget test extends `mobile/test/standalone/my_agents_screen_test.dart`.

---

## Chunk 1: Pure scheduling core (no new deps)

Everything here is pure Dart — no native channels, no new packages. Fully unit-tested.

### Task 1: Russian interval/time parsers (`ru_interval_parse.dart`)

**Files:**
- Create: `mobile/lib/standalone/scheduling/ru_interval_parse.dart`
- Test: `mobile/test/standalone/scheduling/ru_interval_parse_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/ru_interval_parse.dart';

void main() {
  group('parseIntervalHours', () {
    test('digit form', () => expect(parseIntervalHours('каждые 2 часа'), 2));
    test('spelled-out', () => expect(parseIntervalHours('каждые два часа'), 2));
    test('every hour', () => expect(parseIntervalHours('каждый час'), 1));
    test('ежечасно', () => expect(parseIntervalHours('ежечасно'), 1));
    test('no hours -> null', () => expect(parseIntervalHours('по пятницам'), isNull));
  });
  group('parseIntervalMinutes', () {
    test('digit minutes', () => expect(parseIntervalMinutes('каждые 30 минут'), 30));
    test('полчаса', () => expect(parseIntervalMinutes('каждые полчаса'), 30));
    test('no minutes -> null', () => expect(parseIntervalMinutes('каждые 2 часа'), isNull));
  });
  group('parseTimeWindow', () {
    test('с 8 до 22', () => expect(parseTimeWindow('с 8 до 22'), (8, 22)));
    test('вечера shifts end', () => expect(parseTimeWindow('с 8 утра до 10 вечера'), (8, 22)));
    test('unparseable -> null', () => expect(parseTimeWindow('когда захочу'), isNull));
  });
}
```

- [ ] **Step 2: Run test, verify it fails** — `... test/standalone/scheduling/ru_interval_parse_test.dart` → FAIL (file/functions missing).

- [ ] **Step 3: Minimal implementation** (port of `kernel/builder/skill_generator.py:47-78`)

```dart
/// Russian number words for spelled-out intervals (STT often writes words).
const Map<String, int> _ruNum = {
  'один': 1, 'одну': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4,
  'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9,
  'десять': 10, 'двенадцать': 12,
};

/// 'каждые 2 часа' / 'каждый час' / 'ежечасно' → hours; null if none.
int? parseIntervalHours(String text) {
  final t = text.toLowerCase();
  final m = RegExp(r'(\d+)\s*час').firstMatch(t);
  if (m != null) return int.parse(m.group(1)!).clamp(1, 1 << 30);
  for (final e in _ruNum.entries) {
    if (RegExp('\\b${e.key}\\w*\\s+час').hasMatch(t)) return e.value;
  }
  if (t.contains('час') || t.contains('ежечас')) return 1;
  return null;
}

/// 'каждые 30 минут' / 'полчаса' → minutes; null if none.
int? parseIntervalMinutes(String text) {
  final t = text.toLowerCase();
  final m = RegExp(r'(\d+)\s*мин').firstMatch(t);
  if (m != null) return int.parse(m.group(1)!);
  if (t.contains('пол') && t.contains('час')) return 30;
  return null;
}

/// Best-effort window parse: first two hour numbers (≤24); a "вечера" phrasing
/// shifts a single-digit end into PM. Returns (start, end) or null.
(int, int)? parseTimeWindow(String text) {
  final t = text.toLowerCase();
  final nums = RegExp(r'\d{1,2}')
      .allMatches(t)
      .map((m) => int.parse(m.group(0)!))
      .where((n) => n <= 24)
      .toList();
  if (nums.length < 2) return null;
  var s = nums[0];
  var e = nums[1];
  if (t.contains('вечера') && e < 12) e += 12;
  if (s < 0 || s > 23 || e <= s || e > 24) return null;
  return (s, e);
}
```

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Commit** — `git add mobile/lib/standalone/scheduling/ru_interval_parse.dart mobile/test/standalone/scheduling/ru_interval_parse_test.dart && git commit -m "feat(mobile): RU interval/time-window parsers for reminder config"`

### Task 2: `ReminderConfig` + `parseReminderConfig` (`reminder_config.dart`)

**Files:**
- Create: `mobile/lib/standalone/scheduling/reminder_config.dart`
- Test: `mobile/test/standalone/scheduling/reminder_config_test.dart`

- [ ] **Step 1: Write the failing test** — assert the REAL nested shape (grounded in `wizard.py` + `skill_generator.py`):

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_config.dart';

void main() {
  test('reads nested reminders.interval_hours', () {
    final c = parseReminderConfig(
      {'reminders': {'enabled': true, 'interval_hours': 2}, 'time_window': 'с 8 до 22'},
      fallbackMessage: 'пить воду',
    );
    expect(c.intervalHours, 2);
    expect(c.startHour, 8);
    expect(c.endHour, 22);
    expect(c.message, 'пить воду');
  });
  test('falls back to free-text interval', () {
    final c = parseReminderConfig({'interval': 'каждые 3 часа'}, fallbackMessage: 'x');
    expect(c.intervalHours, 3);
  });
  test('sub-hour schedule.cron', () {
    final c = parseReminderConfig({'schedule': {'cron': '*/30 * * * *'}}, fallbackMessage: 'x');
    expect(c.intervalHours, closeTo(0.5, 1e-9));
  });
  test('defaults when nothing parses', () {
    final c = parseReminderConfig({'interval': 'абракадабра'}, fallbackMessage: '  ');
    expect(c.intervalHours, 1);
    expect(c.startHour, 8);
    expect(c.endHour, 22);
    expect(c.message, 'Напоминание'); // empty fallback -> default
  });
  test('clamps out-of-range', () {
    final c = parseReminderConfig(
      {'reminders': {'interval_hours': 999}, 'time_window': 'с 30 до 40'},
      fallbackMessage: 'x',
    );
    expect(c.intervalHours, 24);          // clamped
    expect(c.endHour, greaterThan(c.startHour));
  });
}
```

- [ ] **Step 2: Run test, verify it fails.**

- [ ] **Step 3: Minimal implementation**

```dart
import 'ru_interval_parse.dart';

/// Validated reminder configuration parsed from a voice-built skill.yaml.
class ReminderConfig {
  const ReminderConfig({
    required this.message,
    required this.intervalHours,
    required this.startHour,
    required this.endHour,
  });

  final String message;
  final double intervalHours; // [0.25, 24]
  final int startHour;        // [0, 23]
  final int endHour;          // [startHour+1, 24]
}

double? _toDouble(Object? v) =>
    v is num ? v.toDouble() : (v is String ? double.tryParse(v) : null);

/// Parse the nested wizard config a voice-built reminder carries.
/// Precedence: reminders.interval_hours → free-text `interval` → schedule.cron
/// `*/N` → default 1h. Window from `time_window` free-text or 8..22.
/// [fallbackMessage] (the agent description) is the only message source —
/// the wizard captures none.
ReminderConfig parseReminderConfig(
  Map<dynamic, dynamic> config, {
  required String fallbackMessage,
}) {
  double interval = 1;
  final rem = config['reminders'];
  final sched = config['schedule'];
  if (rem is Map && rem['interval_hours'] != null) {
    interval = _toDouble(rem['interval_hours']) ?? 1;
  } else if (config['interval'] is String) {
    final mins = parseIntervalMinutes(config['interval'] as String);
    final hrs = parseIntervalHours(config['interval'] as String);
    if (mins != null) {
      interval = mins / 60;
    } else if (hrs != null) {
      interval = hrs.toDouble();
    }
  } else if (sched is Map && sched['cron'] is String) {
    final m = RegExp(r'\*/(\d+)').firstMatch(sched['cron'] as String);
    if (m != null) interval = int.parse(m.group(1)!) / 60;
  }
  interval = interval.clamp(0.25, 24);

  int start = 8, end = 22;
  if (config['time_window'] is String) {
    final w = parseTimeWindow(config['time_window'] as String);
    if (w != null) {
      start = w.$1;
      end = w.$2;
    }
  }
  start = start.clamp(0, 23);
  if (end <= start) end = start + 1;
  end = end.clamp(start + 1, 24);

  var msg = fallbackMessage.trim();
  if (msg.isEmpty) msg = 'Напоминание';
  return ReminderConfig(
    message: msg,
    intervalHours: interval,
    startHour: start,
    endHour: end,
  );
}
```

- [ ] **Step 4: Run test, verify PASS.**
- [ ] **Step 5: Commit** — `feat(mobile): parse nested voice-built reminder config`

### Task 3: `nextFireTimes` (`reminder_schedule.dart`)

**Files:**
- Create: `mobile/lib/standalone/scheduling/reminder_schedule.dart`
- Test: `mobile/test/standalone/scheduling/reminder_schedule_test.dart`

- [ ] **Step 1: Write the failing test** (clock injected via `from`; all naive-local):

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_config.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_schedule.dart';

ReminderConfig cfg({double interval = 2, int start = 8, int end = 22}) =>
    ReminderConfig(message: 'm', intervalHours: interval, startHour: start, endHour: end);

void main() {
  test('fires at start then every interval within window', () {
    final from = DateTime(2026, 6, 30, 7); // before window
    final t = nextFireTimes(config: cfg(), from: from, horizonEnd: DateTime(2026, 6, 30, 23), maxCount: 100);
    expect(t.map((d) => d.hour), [8, 10, 12, 14, 16, 18, 20]); // stops before 22
  });
  test('skips times before `from`', () {
    final from = DateTime(2026, 6, 30, 13);
    final t = nextFireTimes(config: cfg(), from: from, horizonEnd: DateTime(2026, 6, 30, 23), maxCount: 100);
    expect(t.first.hour, 14);
  });
  test('rolls into the next day', () {
    final from = DateTime(2026, 6, 30, 21);
    final t = nextFireTimes(config: cfg(), from: from, horizonEnd: DateTime(2026, 7, 1, 12), maxCount: 100);
    expect(t.map((d) => '${d.day}:${d.hour}'), ['1:8', '1:10']);
  });
  test('respects maxCount', () {
    final t = nextFireTimes(config: cfg(), from: DateTime(2026, 6, 30, 7), horizonEnd: DateTime(2026, 7, 10), maxCount: 3);
    expect(t.length, 3);
  });
  test('interval wider than window -> one per day', () {
    final t = nextFireTimes(config: cfg(interval: 20), from: DateTime(2026, 6, 30, 7), horizonEnd: DateTime(2026, 7, 2, 23), maxCount: 100);
    expect(t.map((d) => d.hour), everyElement(8));
    expect(t.length, 3);
  });
}
```

- [ ] **Step 2: Run test, verify it fails.**

- [ ] **Step 3: Minimal implementation**

```dart
import 'reminder_config.dart';

/// PURE. Next fire DateTimes (naive local wall-clock) for a reminder, starting
/// at/after [from], within the daily [startHour, endHour) window, every
/// `intervalHours`, up to [maxCount] and not past [horizonEnd]. `from` is the
/// only "now" — fully deterministic. DST is resolved later by the gateway.
List<DateTime> nextFireTimes({
  required ReminderConfig config,
  required DateTime from,
  required DateTime horizonEnd,
  required int maxCount,
}) {
  final out = <DateTime>[];
  if (maxCount <= 0) return out;
  final stepMs = (config.intervalHours * 3600 * 1000).round();
  if (stepMs <= 0) return out;

  var day = DateTime(from.year, from.month, from.day);
  while (!day.isAfter(horizonEnd)) {
    final dayEnd = DateTime(day.year, day.month, day.day, config.endHour);
    var t = DateTime(day.year, day.month, day.day, config.startHour);
    while (t.isBefore(dayEnd)) {
      if (t.isAfter(horizonEnd)) return out;
      if (!t.isBefore(from)) {
        out.add(t);
        if (out.length >= maxCount) return out;
      }
      t = t.add(Duration(milliseconds: stepMs));
    }
    day = day.add(const Duration(days: 1));
  }
  return out;
}
```

- [ ] **Step 4: Run test, verify PASS.**
- [ ] **Step 5: Commit** — `feat(mobile): pure nextFireTimes reminder schedule`

### Task 4: Notification id-block math (`notification_ids.dart`)

**Files:**
- Create: `mobile/lib/standalone/scheduling/notification_ids.dart`
- Test: `mobile/test/standalone/scheduling/notification_ids_test.dart`

- [ ] **Step 1: Write the failing test**

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';

void main() {
  test('block base is stable and within int32', () {
    final b = blockBase('water');
    expect(b, blockBase('water'));        // stable
    expect(b, lessThan(1 << 31));         // int32-safe
    expect(b & 0xFF, 0);                  // 256-aligned block
  });
  test('slot ids stay inside the agent block', () {
    final b = blockBase('water');
    expect(slotId('water', 0), b);
    expect(slotId('water', 255), b + 255);
    expect(blockSlots, 256);
  });
}
```

- [ ] **Step 2: Run test, verify it fails.**

- [ ] **Step 3: Minimal implementation**

```dart
/// Notifications per agent block (≥ the max per-agent fire budget of 56).
const int blockSlots = 256;

/// Deterministic 256-slot id block for [agentName]. base = (hash15 << 8); max
/// 0x7FFF00 ≈ 8.39M, well within int32. Collisions possible at hundreds of
/// distinct names (15-bit birthday bound) — acceptable on a phone; a collision
/// degrades to a shared block, never crashes.
int blockBase(String agentName) {
  var h = 0;
  for (final c in agentName.codeUnits) {
    h = (h * 31 + c) & 0x7FFF;
  }
  return h << 8;
}

/// The notification id for fire-slot [index] (0..255) of [agentName].
int slotId(String agentName, int index) => blockBase(agentName) + index;
```

- [ ] **Step 4: Run test, verify PASS.**
- [ ] **Step 5: Commit** — `feat(mobile): deterministic notification id blocks`

---

## Chunk 2: Model + import + store (adds `yaml` dep)

### Task 5: Extend `ImportedAgent` with template/config/enabled/snoozeUntil

**Files:**
- Modify: `mobile/lib/standalone/imported_agent.dart`
- Test: `mobile/test/standalone/imported_agent_test.dart` (extend)

- [ ] **Step 1: Add failing tests** (append to existing `main()`):

```dart
  test('new fields round-trip + copyWith', () {
    final a = ImportedAgent(
      name: 'water', description: 'пить воду', skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder', config: {'interval': 'каждые 2 часа'},
      enabled: true, snoozeUntil: DateTime.utc(2026, 6, 30, 12),
    );
    final back = ImportedAgent.fromJson(a.toJson());
    expect(back.template, 'reminder');
    expect(back.config!['interval'], 'каждые 2 часа');
    expect(back.enabled, true);
    expect(back.snoozeUntil, DateTime.utc(2026, 6, 30, 12));
    expect(a.copyWith(enabled: false).enabled, false);
  });
  test('back-compat: Increment-1 JSON (no new keys) loads', () {
    final back = ImportedAgent.fromJson({
      'name': 'chef', 'description': 'повар', 'skillMd': 'md',
      'installedAt': '2026-06-29T00:00:00.000Z',
    });
    expect(back.template, isNull);
    expect(back.enabled, true);       // defaults on
    expect(back.snoozeUntil, isNull);
  });
```

- [ ] **Step 2: Run test, verify it fails.**

- [ ] **Step 3: Implement** — extend the class (keep immutability; null/default coalescing for back-compat):

```dart
class ImportedAgent {
  const ImportedAgent({
    required this.name,
    required this.description,
    required this.skillMd,
    required this.installedAt,
    this.template,
    this.config,
    this.enabled = true,
    this.snoozeUntil,
  });

  final String name;
  final String description;
  final String skillMd;
  final DateTime installedAt;
  final String? template;
  final Map<String, dynamic>? config;
  final bool enabled;
  final DateTime? snoozeUntil;

  ImportedAgent copyWith({bool? enabled, DateTime? snoozeUntil, bool clearSnooze = false}) =>
      ImportedAgent(
        name: name, description: description, skillMd: skillMd, installedAt: installedAt,
        template: template, config: config,
        enabled: enabled ?? this.enabled,
        snoozeUntil: clearSnooze ? null : (snoozeUntil ?? this.snoozeUntil),
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'name': name,
        'description': description,
        'skillMd': skillMd,
        'installedAt': installedAt.toIso8601String(),
        if (template != null) 'template': template,
        if (config != null) 'config': config,
        'enabled': enabled,
        if (snoozeUntil != null) 'snoozeUntil': snoozeUntil!.toIso8601String(),
      };

  factory ImportedAgent.fromJson(Map<String, dynamic> json) => ImportedAgent(
        name: json['name'] as String,
        description: json['description'] as String? ?? '',
        skillMd: json['skillMd'] as String,
        installedAt: DateTime.parse(json['installedAt'] as String),
        template: json['template'] as String?,
        config: (json['config'] as Map?)?.cast<String, dynamic>(),
        enabled: json['enabled'] as bool? ?? true,
        snoozeUntil: json['snoozeUntil'] == null ? null : DateTime.parse(json['snoozeUntil'] as String),
      );
}
```

- [ ] **Step 4: Run test, verify PASS** — also run `test/standalone/agent_store_test.dart` to confirm no regression.
- [ ] **Step 5: Commit** — `feat(mobile): ImportedAgent carries template/config/enabled/snooze`

### Task 6: Extract `skill.yaml` in `bundle_importer` (adds `yaml`)

**Files:**
- Modify: `mobile/lib/standalone/bundle_importer.dart`
- Test: `mobile/test/standalone/bundle_importer_test.dart` (extend)

- [ ] **Step 1: Add the `yaml` dep** — `cd mobile && "C:/src/flutter/flutter/bin/flutter.bat" pub add yaml` → confirm `yaml:` appears in `pubspec.yaml`.

- [ ] **Step 2: Write the failing test** — build a `.tar.gz` payload in-test carrying SKILL.md + skill.yaml with the REAL nested shape, base64url-encode it, assert `template`/`config` extracted; and a SKILL.md-only payload → `template == null`; a corrupt skill.yaml → still imports conversational-only. (Reuse the helper already used by the existing importer tests to build a payload; if none, add a small `_payload(Map<String,String> files)` helper using `package:archive` `TarEncoder` + `GZipEncoder` + `base64Url`.)

```dart
  test('extracts template + nested config from skill.yaml', () async {
    final skillMd = '---\nname: water\ndescription: пить воду\n---\n# water\n';
    final skillYaml = 'template: reminder\n'
        'description: пить воду\n'
        'config:\n'
        '  interval: каждые 2 часа\n'
        '  time_window: с 8 до 22\n'
        '  reminders:\n    enabled: true\n    interval_hours: 2\n';
    final agent = await importBundle(_payload({
      'water/SKILL.md': skillMd,
      'water/skill.yaml': skillYaml,
    }));
    expect(agent.template, 'reminder');
    expect((agent.config!['reminders'] as Map)['interval_hours'], 2);
  });
  test('SKILL.md-only bundle -> conversational-only (template null)', () async {
    final agent = await importBundle(_payload({
      'chef/SKILL.md': '---\nname: chef\ndescription: повар\n---\n# chef\n',
    }));
    expect(agent.template, isNull);
  });
  test('corrupt skill.yaml does not fail the import', () async {
    final agent = await importBundle(_payload({
      'water/SKILL.md': '---\nname: water\ndescription: x\n---\n# water\n',
      'water/skill.yaml': '::: not yaml :::\n  - [unbalanced',
    }));
    expect(agent.name, 'water');
    expect(agent.template, isNull); // ignored, not fatal
  });
```

- [ ] **Step 3: Run test, verify it fails.**

- [ ] **Step 4: Implement** — after the existing SKILL.md parse (`bundle_importer.dart`), before `return ImportedAgent(...)`, add skill.yaml extraction. Keep the importer pure (decode only) and wrap parsing so a malformed yaml never throws out of `importBundle`:

```dart
import 'package:yaml/yaml.dart';
// ...
String? template;
Map<String, dynamic>? config;
final yamlEntry = archive.files.where(
  (f) => f.isFile && (f.name == 'skill.yaml' || f.name.endsWith('/skill.yaml')),
);
if (yamlEntry.isNotEmpty) {
  try {
    final text = utf8.decode(yamlEntry.first.content as List<int>);
    final doc = loadYaml(text);
    if (doc is YamlMap) {
      template = doc['template']?.toString();
      final c = doc['config'];
      if (c is YamlMap) config = _deepMap(c);
    }
  } catch (_) {
    // Malformed skill.yaml is non-fatal: the agent imports conversational-only.
    template = null;
    config = null;
  }
}

return ImportedAgent(
  name: name,
  description: (fm['description'] ?? '').trim(),
  skillMd: md,
  installedAt: DateTime.now().toUtc(),
  template: template,
  config: config,
);
```

Add a small recursive `YamlMap`→`Map<String,dynamic>` converter (so nested `reminders`/`schedule` survive as plain maps the config parser reads):

```dart
Map<String, dynamic> _deepMap(YamlMap m) {
  final out = <String, dynamic>{};
  m.nodes.forEach((k, v) {
    out[k.toString()] = _deepVal(v.value);
  });
  return out;
}
dynamic _deepVal(dynamic v) {
  if (v is YamlMap) return _deepMap(v);
  if (v is YamlList) return v.map(_deepVal).toList();
  return v;
}
```

- [ ] **Step 5: Run test, verify PASS** — also re-run the full existing `bundle_importer_test.dart` (zip-slip / bomb / utf8 guards must still pass).
- [ ] **Step 6: Commit** — `feat(mobile): bundle_importer extracts skill.yaml template+config`

### Task 7: Confirm store round-trips the new fields

**Files:**
- Test: `mobile/test/standalone/agent_store_test.dart` (extend)

- [ ] **Step 1: Add a failing test** — save a reminder agent (template/config/enabled/snooze) → `get` returns them intact; and a hand-written old-format JSON file in the temp dir loads (back-compat). (No code change expected — `save`/`list`/`get` are opaque JSON; this test locks the contract.)

```dart
  test('round-trips reminder fields', () async {
    final dir = await Directory.systemTemp.createTemp('kali_agents_test');
    final store = FileAgentStore(baseDir: dir);
    await store.save(ImportedAgent(
      name: 'water', description: 'пить', skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder', config: {'reminders': {'interval_hours': 2}},
      enabled: false, snoozeUntil: DateTime.utc(2026, 6, 30, 9),
    ));
    final got = (await store.get('water'))!;
    expect(got.template, 'reminder');
    expect(got.enabled, false);
    expect(got.snoozeUntil, DateTime.utc(2026, 6, 30, 9));
  });
```

- [ ] **Step 2: Run test** — expect PASS immediately (proves the opaque round-trip). If it fails, fix `toJson/fromJson` from Task 5, not the store.
- [ ] **Step 3: Commit** — `test(mobile): lock reminder-field store round-trip`

---

## Chunk 3: Gateway + scheduler + wiring (adds `flutter_local_notifications` + `timezone`)

### Task 8: `NotificationGateway` interface + fake; native `LocalNotificationGateway`

**Files:**
- Create: `mobile/lib/standalone/scheduling/notification_gateway.dart`
- Test: `mobile/test/standalone/scheduling/fake_notification_gateway.dart` (a reusable test double)

- [ ] **Step 1: Add deps** — `... pub add flutter_local_notifications timezone` → confirm both in `pubspec.yaml`.

- [ ] **Step 2: Define the interface** (no test needed for an abstract class; the contract is exercised by the scheduler tests via the fake):

```dart
/// A registered (or cancelled) local notification, abstracted so the scheduler
/// is testable without the native channel.
abstract class NotificationGateway {
  Future<bool> requestPermission();
  Future<void> scheduleAt(int id, DateTime when, String title, String body);
  /// Cancels the whole 256-id block for [agentName].
  Future<void> cancelForAgent(String agentName);
  Future<int> pendingCount();
}
```

- [ ] **Step 3: Write the reusable fake** (used by Task 9 tests):

```dart
import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';

class FakeNotificationGateway implements NotificationGateway {
  final Map<int, DateTime> scheduled = {};
  bool permission = true;
  @override
  Future<bool> requestPermission() async => permission;
  @override
  Future<void> scheduleAt(int id, DateTime when, String t, String b) async => scheduled[id] = when;
  @override
  Future<void> cancelForAgent(String name) async {
    final base = blockBase(name);
    scheduled.removeWhere((id, _) => id >= base && id < base + blockSlots);
  }
  @override
  Future<int> pendingCount() async => scheduled.length;
}
```

- [ ] **Step 4: Implement `LocalNotificationGateway`** (native; validated in the live test, not unit-tested). In the same file:

```dart
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/timezone.dart' as tz;
import 'notification_ids.dart';

class LocalNotificationGateway implements NotificationGateway {
  LocalNotificationGateway(this._plugin);
  final FlutterLocalNotificationsPlugin _plugin;

  static const _details = NotificationDetails(
    android: AndroidNotificationDetails('kali_reminders', 'Напоминания',
        importance: Importance.high, priority: Priority.high),
    iOS: DarwinNotificationDetails(),
  );

  @override
  Future<bool> requestPermission() async {
    final ios = await _plugin
        .resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>()
        ?.requestPermissions(alert: true, badge: true, sound: true);
    final android = await _plugin
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
    return ios ?? android ?? true;
  }

  @override
  Future<void> scheduleAt(int id, DateTime when, String title, String body) =>
      _plugin.zonedSchedule(
        id, title, body, tz.TZDateTime.from(when, tz.local), _details,
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
      );

  @override
  Future<void> cancelForAgent(String name) async {
    final base = blockBase(name);
    for (var i = 0; i < blockSlots; i++) {
      await _plugin.cancel(base + i);
    }
  }

  @override
  Future<int> pendingCount() async =>
      (await _plugin.pendingNotificationRequests()).length;
}
```

- [ ] **Step 5: Commit** — `feat(mobile): NotificationGateway interface + local + fake`

### Task 9: `ReminderScheduler` (`reminder_scheduler.dart`) — the core logic

**Files:**
- Create: `mobile/lib/standalone/scheduling/reminder_scheduler.dart`
- Test: `mobile/test/standalone/scheduling/reminder_scheduler_test.dart`

- [ ] **Step 1: Write the failing tests** (fake gateway + in-memory/temp store):

```dart
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_scheduler.dart';
import 'fake_notification_gateway.dart';

Future<FileAgentStore> _store() async =>
    FileAgentStore(baseDir: await Directory.systemTemp.createTemp('sched'));

ImportedAgent _reminder(String n, {bool enabled = true}) => ImportedAgent(
      name: n, description: 'пить воду', skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder',
      config: {'reminders': {'interval_hours': 2}, 'time_window': 'с 8 до 22'},
      enabled: enabled,
    );

void main() {
  test('syncAll schedules an enabled reminder', () async {
    final store = await _store();
    await store.save(_reminder('water'));
    final gw = FakeNotificationGateway();
    final s = ReminderScheduler(store: store, gateway: gw);
    await s.syncAll(DateTime(2026, 6, 30, 7));
    expect(gw.scheduled, isNotEmpty);
    expect(gw.scheduled.keys.every((id) => id >= blockBase('water') && id < blockBase('water') + blockSlots), true);
  });

  test('disabled / non-reminder agents schedule nothing and get cancel-passed', () async {
    final store = await _store();
    await store.save(_reminder('off', enabled: false));
    await store.save(ImportedAgent(name: 'chat', description: 'x', skillMd: 'md', installedAt: DateTime.utc(2026, 6, 30)));
    final gw = FakeNotificationGateway();
    await ReminderScheduler(store: store, gateway: gw).syncAll(DateTime(2026, 6, 30, 7));
    expect(gw.scheduled, isEmpty);
  });

  test('setEnabled(false) cancels; idempotent re-sync', () async {
    final store = await _store();
    await store.save(_reminder('water'));
    final gw = FakeNotificationGateway();
    final s = ReminderScheduler(store: store, gateway: gw);
    await s.syncAll(DateTime(2026, 6, 30, 7));
    final n = gw.scheduled.length;
    await s.syncAll(DateTime(2026, 6, 30, 7));
    expect(gw.scheduled.length, n); // idempotent
    await s.setEnabled('water', false);
    expect(gw.scheduled, isEmpty);
    expect((await store.get('water'))!.enabled, false);
  });

  test('snooze shifts the first fire and persists', () async {
    final store = await _store();
    await store.save(_reminder('water'));
    final gw = FakeNotificationGateway();
    final s = ReminderScheduler(store: store, gateway: gw);
    await s.snooze('water', const Duration(hours: 3), DateTime(2026, 6, 30, 9));
    final first = (gw.scheduled.values.toList()..sort()).first;
    expect(first.isAfter(DateTime(2026, 6, 30, 11, 59)), true); // pushed past 12:00
    expect((await store.get('water'))!.snoozeUntil, isNotNull);
  });

  test('global 56-budget split across K agents', () async {
    final store = await _store();
    for (var i = 0; i < 4; i++) {
      await store.save(_reminder('a$i'));
    }
    final gw = FakeNotificationGateway();
    await ReminderScheduler(store: store, gateway: gw).syncAll(DateTime(2026, 6, 30, 7));
    // 56 ~/ 4 = 14 per agent, capped by the 7d horizon (7 fires/day * 7d = 49 > 14) → 14 each.
    expect(gw.scheduled.length, lessThanOrEqualTo(56));
  });
}
```

- [ ] **Step 2: Run tests, verify they fail.**

- [ ] **Step 3: Minimal implementation**

```dart
import 'package:kali_mobile/standalone/agent_store.dart';
import 'reminder_config.dart';
import 'reminder_schedule.dart';
import 'notification_gateway.dart';
import 'notification_ids.dart';

const int kGlobalPendingBudget = 56;
const Duration _kHorizon = Duration(days: 7);

/// Syncs all enabled reminder agents to the OS via [gateway]. Idempotent:
/// cancel-then-reschedule on every call (import / app-resume / toggle / snooze).
class ReminderScheduler {
  ReminderScheduler({required this.store, required this.gateway});
  final AgentStore store;
  final NotificationGateway gateway;

  Future<void> syncAll(DateTime now) async {
    final agents = await store.list();
    final active = agents.where((a) => a.template == 'reminder' && a.enabled).toList();

    // Honest upper edge: cap the active set to the soonest GLOBAL_PENDING_BUDGET.
    final capped = active.length > kGlobalPendingBudget
        ? (active..sort((a, b) => a.name.compareTo(b.name))).sublist(0, kGlobalPendingBudget)
        : active;
    final k = capped.length;
    final perAgent = k == 0 ? 0 : (kGlobalPendingBudget ~/ k).clamp(1, blockSlots);
    final cappedNames = capped.map((a) => a.name).toSet();

    for (final a in agents) {
      await gateway.cancelForAgent(a.name); // clears stale ids for everyone
      if (!cappedNames.contains(a.name)) continue;
      final cfg = parseReminderConfig(a.config ?? const {}, fallbackMessage: a.description);
      final from = (a.snoozeUntil != null && a.snoozeUntil!.isAfter(now)) ? a.snoozeUntil! : now;
      final times = nextFireTimes(
        config: cfg, from: from, horizonEnd: now.add(_kHorizon), maxCount: perAgent);
      for (var i = 0; i < times.length; i++) {
        await gateway.scheduleAt(slotId(a.name, i), times[i], a.name, cfg.message);
      }
    }
  }

  Future<void> setEnabled(String agentName, bool enabled, [DateTime? now]) async {
    final a = await store.get(agentName);
    if (a == null) return;
    await store.save(a.copyWith(enabled: enabled));
    await syncAll(now ?? DateTime.now());
  }

  Future<void> snooze(String agentName, Duration d, [DateTime? now]) async {
    final clock = now ?? DateTime.now();
    final a = await store.get(agentName);
    if (a == null) return;
    await store.save(a.copyWith(snoozeUntil: clock.add(d)));
    await syncAll(clock);
  }
}
```

> Implementation note for the worker: the `now` params on `setEnabled`/`snooze` exist so tests inject a fixed clock; production callers omit them. This is the only `DateTime.now()` in the file and it never runs under test.

- [ ] **Step 4: Run tests, verify PASS.**
- [ ] **Step 5: Commit** — `feat(mobile): ReminderScheduler (sync/toggle/snooze + global budget)`

### Task 10: Wire scheduler into import + providers + app-resume

**Files:**
- Modify: `mobile/lib/presentation/my_agents_screen.dart` (add `notificationGatewayProvider`, `reminderSchedulerProvider`)
- Modify: `mobile/lib/core/deep_link_service.dart` (`_importStandalone` → after `importOnDevice`, call `scheduler.syncAll`)
- Modify: `mobile/lib/presentation/main_screen.dart` (resume observer → `syncAll`)
- Test: `mobile/test/standalone/scheduling/import_triggers_sync_test.dart`

- [ ] **Step 1: Add providers** (in `my_agents_screen.dart`, beside the existing `agentStoreProvider`):

```dart
final notificationGatewayProvider = Provider<NotificationGateway>(
  (ref) => LocalNotificationGateway(FlutterLocalNotificationsPlugin()));

final reminderSchedulerProvider = Provider<ReminderScheduler>((ref) => ReminderScheduler(
      store: ref.read(agentStoreProvider),
      gateway: ref.read(notificationGatewayProvider),
    ));
```

- [ ] **Step 2: Write the failing test** — a pure helper `Future<void> syncAfterImport(ReminderScheduler s, DateTime now)` (or assert via a small seam) that the standalone import path triggers a sync. Simplest testable seam: extract `Future<void> scheduleImported(ReminderScheduler scheduler, DateTime now)` and test it calls `syncAll` (fake gateway shows scheduled entries after a reminder is in the store). Keep the deep-link UI glue thin and delegate to this tested seam.

```dart
  test('importing a reminder then syncing schedules it', () async {
    final store = await _store();              // helper as in Task 9
    await store.save(_reminder('water'));
    final gw = FakeNotificationGateway();
    await ReminderScheduler(store: store, gateway: gw).syncAll(DateTime(2026, 6, 30, 7));
    expect(gw.scheduled, isNotEmpty);
  });
```

- [ ] **Step 3: Implement the glue** — in `_importStandalone` (`deep_link_service.dart`), after `importOnDevice(...)` succeeds, request permission once and `await ref.read(reminderSchedulerProvider).syncAll(DateTime.now())` (guard: only if the imported agent `template == 'reminder'`, else skip — conversational-only is unchanged). In `main_screen.dart`, add `WidgetsBindingObserver`; on `AppLifecycleState.resumed` call `ref.read(reminderSchedulerProvider).syncAll(DateTime.now())`.

- [ ] **Step 4: Run test + full suite, verify PASS.**
- [ ] **Step 5: Commit** — `feat(mobile): trigger reminder sync on import + app resume`

---

## Chunk 4: UI + native config + live-verify

### Task 11: Reminder controls in «Мои агенты» (toggle + next-fire + snooze)

**Files:**
- Modify: `mobile/lib/presentation/my_agents_screen.dart` (`_agentTile` for reminder agents)
- Test: `mobile/test/standalone/my_agents_screen_test.dart` (extend)

- [ ] **Step 1: Write the failing widget test** — pump `MyAgentsScreen` with `agentStoreProvider` overridden to a store holding a reminder agent + `notificationGatewayProvider` overridden to the fake; assert a `Switch` is shown and a next-fire label renders; toggling the switch calls `setEnabled` (fake gateway empties). Use the existing `my_agents_screen_test.dart` setup as the harness template.

- [ ] **Step 2: Run test, verify it fails.**

- [ ] **Step 3: Implement** — in `_agentTile`, when `agent.template == 'reminder'`, render a trailing `Switch` (value `agent.enabled`) wired to `reminderSchedulerProvider.setEnabled`, a subtitle line "Следующее: <HH:mm>" computed from `nextFireTimes(..., maxCount: 1)`, and a snooze affordance (an in-app "Отложить на час" action calling `scheduler.snooze(name, Duration(hours: 1))`). Non-reminder agents keep the current chevron→chat tile unchanged. Add a small "нужно разрешение на уведомления" inline note when `requestPermission()` returns false (honest, routes to settings). Keep strings Russian and route new l10n keys through `l10n.dart` like the existing `myAgents*` keys.

- [ ] **Step 4: Run test + full suite, verify PASS.**
- [ ] **Step 5: Commit** — `feat(mobile): reminder toggle/next-fire/snooze in Мои агенты`

### Task 12: Native notification config

**Files:**
- Modify: `mobile/android/app/src/main/AndroidManifest.xml`
- Modify: `mobile/ios/Runner/AppDelegate.swift`, `mobile/ios/Runner/Info.plist`
- Modify: app bootstrap (where `runApp` is called) — `tz.initializeTimeZones()` + set local zone before first schedule.

- [ ] **Step 1:** Android — add `POST_NOTIFICATIONS` permission (API 33+), the `flutter_local_notifications` `ScheduledNotificationReceiver` + `ScheduledNotificationBootReceiver` (with `RECEIVE_BOOT_COMPLETED`) per the package README so scheduled notifications survive reboot.
- [ ] **Step 2:** iOS — in `AppDelegate.swift` set `UNUserNotificationCenter.current().delegate` and register the plugin per README; ensure background modes are NOT needed (pure scheduled notifications don't require them).
- [ ] **Step 3:** Bootstrap — call `tz.initializeTimeZones()` and set `tz.setLocalLocation(tz.getLocation(<device tz>))` once at startup (use `flutter_timezone` if needed to read the device zone, OR default to a sane local lookup) BEFORE any `zonedSchedule`.
- [ ] **Step 4: Verify build** — `cd mobile && "C:/src/flutter/flutter/bin/flutter.bat" analyze` (0 new errors) and `... test` (full suite green). Native scheduling itself is verified in Task 13 (live), not in unit tests.
- [ ] **Step 5: Commit** — `chore(mobile): native config for scheduled local notifications`

### Task 13: Grounding + live-verify (deferred to Vasily / real device)

- [ ] **Step 1 (grounding — do early if a desktop is reachable):** Export a real voice-built reminder from the desktop builder and inspect the `.tar.gz`: confirm `skill.yaml` carries `template: reminder` + a nested `config:` with `interval` / `time_window` / `reminders.interval_hours` exactly as Task 2/6 assume. If the real keys differ, fix `parseReminderConfig` + the importer test fixture before shipping. (Static reads of `wizard.py` + `skill_generator.py` already confirm the shape; this confirms the serialized artifact.)
- [ ] **Step 2 (live — Vasily, `kali_test_34` / real phone):** standalone import a real shared reminder → grant the notification permission → confirm a real notification fires at the scheduled time with the app backgrounded/killed; toggle off → no further fires; snooze → next fire shifts.
- [ ] **Step 3:** Record the live result in the session handoff. (No commit; this is verification.)

---

## Final: full-suite gate + push

- [ ] Run the **full mobile suite**: `cd mobile && "C:/src/flutter/flutter/bin/flutter.bat" test` → expect the prior 60 + all new tests green, 0 analyze errors in touched files.
- [ ] Confirm `pytest -m core_loop` (desktop) still **13 passed** (no desktop code changed, but verify nothing leaked).
- [ ] Push `main` (backup): `git push`.
- [ ] Update memory + write the session handoff.

## Anti-pivot checkpoint
Reminders run only on the phone (local notifications + local store), zero server, zero LLM in the execution loop, no dev-integration / OS-assistant / crypto surface. Honest about OS background limits (pre-scheduled + app-open top-up; no perpetual-background promise). ✓
