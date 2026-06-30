# KALI — Mobile Standalone: Reminder Runtime (WS-4.7 Increment 2) — Design Spec

**Date:** 2026-06-30
**Status:** Design — approved scope (Vasily), pending spec review + writing-plans
**Source:** Phase 2 of the remediation plan ([`docs/public-launch/2026-06-29-remediation-plan.md`](../../public-launch/2026-06-29-remediation-plan.md)). Continues [`2026-06-29-mobile-standalone-receive-run-design.md`](2026-06-29-mobile-standalone-receive-run-design.md) (Increment 1 — on-device receive + conversational run, merged `2aa14d3`). Architecture = Option B (on-device lite engine, no ML port) per [`docs/public-launch/2026-06-19-mobile-standalone-design.md`](../../public-launch/2026-06-19-mobile-standalone-design.md).

## 1. Problem & decision
Increment 1 lets a desktop-less phone **import** a shared agent and **chat** with it (cloud LLM, SKILL.md = system prompt). But a received agent still **does nothing on its own** — a `reminder` agent ("попей воды каждые 2 часа") cannot fire. The make-or-break UGC promise is "создал голосом → работает → друг поставил и *оно работает*"; Increment 1 delivered chat, this increment delivers the first real **action**.

**Decision (Vasily, brainstorm 2026-06-30):**
- **Scheduled-first** mechanic: autonomous scheduled execution before conversational tool-dispatch.
- **`reminder` only** in this increment (cleanest slice; tracker/notifier/monitor and the LLM tool-dispatch path are later increments).
- **Pre-scheduled local notifications + app-open top-up**: the OS delivers each fire at its exact time even when the app is killed; the horizon is re-topped-up whenever the app resumes (no background worker dependency).
- **UI control** (toggle on/off + snooze), **no LLM** in the execution or control loop.

The desktop reminder semantics are **re-expressed**, not ported: desktop is pull-based (`ReminderTemplate._check()` asks "should I fire now?" on a scheduler tick — [`kernel/skill_templates/reminder.py`](../../../kernel/skill_templates/reminder.py)); mobile is push-based (fire times are pre-computed from the same config and registered with the OS). The shared contract is the **config semantics** (message, `interval_hours`, `start_hour`, `end_hour`, snooze), not the code path.

## 2. Scope / non-goals
### In scope
- Extract `skill.yaml` (`template` + `config`) from the imported bundle alongside the existing SKILL.md.
- A typed, validated `ReminderConfig`.
- A **pure** schedule function computing the next fire times from config + an injected "now".
- A local-notification gateway (behind an interface) over `flutter_local_notifications` + `timezone`.
- A scheduler service that syncs all enabled reminder agents to the OS (on import, app-resume, toggle, snooze).
- "Мои агенты" UI: per-reminder-agent toggle + next-fire time + snooze; notification-permission request + honest denied state.

### Non-goals (YAGNI — later increments)
- Conversational tool-dispatch / the Dart LLM-tool runtime (tracker `log/summary`, LLM emitting `tool_call`s). Explicitly deferred — adding it here would blur the increment.
- `notifier` (telegram delivery — keys/network), `monitor` (network/SSRF), `tracker`, `logger`.
- A background worker (`workmanager` / `BGTaskScheduler`). App-open top-up suffices; background is best-effort anyway (Doze/OEM-killers) and adds native deps — revisit only if rarely-opened reminders prove to be a real problem.
- Build-an-agent-by-voice on the phone; dashboard; cloud catalog.
- Changing the tethered (desktop-paired) path, the `kali://pair` path, or the Increment-1 conversational chat — this is parallel, standalone-only.

## 3. Architecture & components
New units under `mobile/lib/standalone/scheduling/` (each independently testable, ≤~250 lines):

### 3.1 `reminder_config.dart`
```dart
class ReminderConfig {
  final String message;
  final double intervalHours;   // default 1
  final int startHour;          // default 8   (0..23)
  final int endHour;            // default 22  (1..24, > startHour)
}
/// Parse + validate a skill.yaml `config:` map. Clamps out-of-range values to
/// safe defaults (never throws on bad data — validate at the boundary,
/// degrade honestly). Defaults mirror kernel/skill_templates/reminder.py.
ReminderConfig parseReminderConfig(Map<dynamic, dynamic> config);
```
Validation rules (boundary): `intervalHours` → clamp to `[0.25, 24]`; `startHour` → `[0,23]`; `endHour` → `[startHour+1, 24]`; empty `message` → a sensible default ("Напоминание"). Out-of-range inputs are clamped, not rejected — a malformed bundle still yields a working (if defaulted) reminder.

### 3.2 `reminder_schedule.dart`
```dart
/// PURE. The next fire DateTimes for a reminder, in local wall-clock time.
/// Fires at startHour, then every intervalHours, while hour < endHour, each day,
/// starting from `from`, up to `maxCount` times and not beyond `horizonEnd`.
/// `from` is injected (no clock access) so this is fully deterministic/testable.
List<DateTime> nextFireTimes({
  required ReminderConfig config,
  required DateTime from,
  required DateTime horizonEnd,
  required int maxCount,
});
```
No native, no I/O, no `DateTime.now()` — the single source of "now" is `from`. This is where every scheduling edge case is tested (window boundaries, day rollover, interval arithmetic, horizon/maxCount truncation, snooze offset applied by the caller via `from`).

### 3.3 `notification_gateway.dart`
```dart
abstract class NotificationGateway {
  Future<bool> requestPermission();
  Future<void> scheduleAt(int id, DateTime when, String title, String body);
  Future<void> cancelForAgent(String agentName);   // cancels this agent's id range
  Future<int> pendingCount();
}
/// LocalNotificationGateway: flutter_local_notifications + timezone
/// (zonedSchedule on tz.local). The interface keeps tests off the native
/// channel — the scheduler is tested against a fake gateway.
```
Deterministic id scheme so re-sync cleanly replaces an agent's pending notifications: `base = stableHash(agentName) masked to a per-agent block`, fire-slot `id = base + slotIndex`. `cancelForAgent` cancels the agent's block. (Concrete id math is a plan detail; constraint: collision-free across the expected agent count, within int32.)

### 3.4 `reminder_scheduler.dart`
```dart
class ReminderScheduler {
  Future<void> syncAll(DateTime now);          // import / resume / toggle
  Future<void> setEnabled(String agent, bool); // toggle → persist + sync
  Future<void> snooze(String agent, Duration); // persist snoozeUntil + sync
}
```
`syncAll`: read the store; for each agent with `template == 'reminder'` and `enabled == true`, compute `nextFireTimes(from: max(now, snoozeUntil), horizon: now + 7d, maxCount: <iOS-safe budget>)` and `cancelForAgent` → `scheduleAt(...)` each. Disabled/non-reminder agents are cancelled/skipped. Idempotent: safe to call on every resume.

### 3.5 Extensions to existing Increment-1 units (surgical)
- **`imported_agent.dart`** — add `String? template`, `Map<String, dynamic>? config`, `bool enabled` (default `true`), `DateTime? snoozeUntil`. `toJson/fromJson` stay backward-compatible (Increment-1 records have no template → `template == null` → conversational-only, unchanged behaviour). Immutable + a `copyWith` for enabled/snooze updates.
- **`bundle_importer.dart`** — after locating SKILL.md, if a `skill.yaml` (or `<name>/skill.yaml`) entry exists, parse `template` + `config` from it (add the pure-Dart `yaml` package — the current flat `_frontmatter` parser cannot read nested `config:`). Keep the importer pure (decode only). A missing/malformed `skill.yaml` must **not** fail the import — the agent still imports as conversational-only.
- **`agent_store.dart`** — persists the new fields via the existing per-agent JSON (`save()` already overwrites). Add no new storage mechanism.
- **App lifecycle** — a `WidgetsBindingObserver` calls `scheduler.syncAll(now)` on `AppLifecycleState.resumed`. This is the app-open top-up.
- **Riverpod** — providers for `NotificationGateway`, `ReminderScheduler`; "Мои агенты" reads agent + enabled state.

## 4. Data flow
```
import → bundle_importer(SKILL.md + skill.yaml) → ImportedAgent{template:'reminder', config, enabled:true}
       → store.save → scheduler.syncAll(now)
app resume → scheduler.syncAll(now)                 (horizon top-up)
toggle off → setEnabled(false) → store + cancelForAgent
snooze (UI button / notification action) → snooze(agent, +N) → store(snoozeUntil) → syncAll
fire time → OS delivers the local notification       (app may be killed)
```

## 5. OS background limits — stated honestly (anti-pivot)
- Exact timing is guaranteed **only** by pre-scheduled local notifications (the OS delivers them with the app killed). There is no promise of guaranteed perpetual background execution.
- The pending-notification horizon is bounded (iOS caps total pending at **64** across the app) → schedule ~7 days ahead; top-up on each app open.
- **Honest UX disclaimer:** if the app is not opened for longer than the scheduled horizon, the queue runs dry until next open (a rare case). We say this rather than imply infinite background.
- Notification permission denied → the agent still imports; its toggle shows "нужно разрешение на уведомления" and routes to settings. No silent failure.

## 6. Error handling (honest, never crash)
| Failure | Behavior |
|---|---|
| Bundle has no `skill.yaml` (Increment-1 / a SKILL.md skill) | `template == null` → conversational-only, no scheduling (backward compatible). |
| `skill.yaml` with `template != reminder` | Stored, not scheduled; UI is honest ("этот агент пока только беседует"). |
| Malformed `config` (hours/interval out of range) | Clamped to safe defaults + honest note; never crashes the import or sync. |
| Malformed / unparseable `skill.yaml` | Ignored; agent imports as conversational-only (import never fails on it). |
| Notification permission denied | Imports; toggle shows "нужно разрешение" → settings route. |
| Horizon exhausted (app unopened > horizon) | Re-topped-up on next open; UX disclaimer sets the expectation. |

## 7. Anti-pivot ✓
Reminders run **only on the phone** — local notifications, local file store, zero KALI server, zero LLM in the execution path. This makes "your data and your agents stay on your phone" literally true and is honestly disclosable. It strengthens exactly the moat axes competitors leave unoccupied (voice-created agent + mobile + UGC + local data), and adds no dev-integration / OS-assistant / crypto surface.

## 8. Testing (`flutter test` via `C:\src\flutter\flutter\bin\flutter.bat`)
- **`reminder_schedule` (pure, the core):** fires at `start_hour` then every `interval`; stops at `end_hour`; rolls to the next day; respects `maxCount` + `horizonEnd`; boundary hours (start==end-1, interval > window); snooze applied via `from`. Many deterministic cases — clock injected.
- **`reminder_config`:** parse + defaults; clamps each out-of-range field; empty message → default; non-numeric values degrade, don't throw.
- **`bundle_importer`:** a **real** voice-built reminder bundle → `template=='reminder'` + populated `config`; a SKILL.md-only bundle → `template==null` (back-compat preserved); a bundle with a corrupt `skill.yaml` → still imports conversational-only.
- **`agent_store`:** round-trips `template`/`config`/`enabled`/`snoozeUntil`; old (Increment-1) JSON without the new keys still loads.
- **`reminder_scheduler` (fake gateway):** `syncAll` registers the schedule-function's times; `setEnabled(false)` → `cancelForAgent`; `snooze` shifts the first fire; a non-reminder/disabled agent schedules nothing; re-`syncAll` is idempotent (cancel-then-reschedule).
- **Widget:** "Мои агенты" shows a reminder row with toggle + next-fire; permission-denied state renders the honest prompt.
- **Live (deferred — Vasily, real device `kali_test_34`):** import a real shared reminder → grant permission → a real notification fires at the scheduled time with the app backgrounded/killed.

## 9. Grounding items for the implementer
1. **Round-trip a real bundle.** Export a voice-built reminder from the desktop and confirm its `.tar.gz` carries `skill.yaml` with `template: reminder` + a populated `config` (high confidence from [`kernel/skill_executor.py`](../../../kernel/skill_executor.py) `TEMPLATE_REGISTRY` + [`kernel/skills/publisher.py`](../../../kernel/skills/publisher.py) `_add_bundle_members`, which adds `manifest.yaml`+`skill.yaml` for voice-built skills — but verify on a real artifact before relying on it).
2. **New dependencies:** `flutter_local_notifications`, `timezone`, `yaml`. Confirm they are absent from `mobile/pubspec.yaml`; the native config (iOS permissions/`AppDelegate`, Android `AndroidManifest` receivers + `POST_NOTIFICATIONS` on API 33+) is an honest, separate setup step — call it out in the plan.
3. **Notification id scheme** + `timezone` init (`tz.initializeTimeZones()` + set `tz.local`) before any `zonedSchedule`.
4. **Snooze as a notification action** needs a native background-action handler. If that proves heavy, the plan may degrade snooze to an **in-app** snooze button (tapping the notification opens the agent) and defer the on-notification action — note the chosen path explicitly.
5. **Config key names:** read the actual keys a voice-built reminder writes into `skill.yaml` `config:` (expected `message`, `interval_hours`, `start_hour`, `end_hour` per `reminder.py`), and match them exactly in `parseReminderConfig`.
