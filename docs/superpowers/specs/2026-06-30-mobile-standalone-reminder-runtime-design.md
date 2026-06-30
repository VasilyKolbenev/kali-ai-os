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
/// Parse + validate the skill.yaml `config:` map a voice-built reminder
/// actually carries. Clamps out-of-range values to safe defaults (never throws
/// on bad data — validate at the boundary, degrade honestly).
/// [fallbackMessage] is the agent description (see message-source note below).
ReminderConfig parseReminderConfig(
  Map<dynamic, dynamic> config, {
  required String fallbackMessage,
});
```

**Real config shape (grounded in `kernel/builder/wizard.py` + `kernel/builder/skill_generator.py`).** A voice-built `reminder` does NOT produce flat `message`/`start_hour`/`end_hour`/`interval_hours`. The wizard ([`wizard.py:84-88`](../../../kernel/builder/wizard.py) `_skill_questions` + `_question_to_key`) records the two free-text answers as:
- `interval` — free-text Russian (e.g. `"каждые 2 часа"`) from "Как часто напоминать?".
- `time_window` — free-text Russian (e.g. `"с 8 утра до 10 вечера"`) from "В какое время начинать и заканчивать?".

then [`skill_generator._with_schedule`](../../../kernel/builder/skill_generator.py) parses the interval and, for whole-hour intervals, injects `reminders: {enabled: true, interval_hours: <int>}` (or, for sub-hour, top-level `schedule: {cron: "*/<min> * * * *"}`). The wizard **never captures a reminder message** — the only human text is the agent `description` (the raw voice request).

**Parse contract (exact precedence — must match the producer, not `reminder.py`):**
- `intervalHours` ← `config['reminders']['interval_hours']` if present; else a Dart port of `_parse_interval_hours` / `_parse_interval_minutes` applied to `config['interval']` (minutes → `min/60`); else `config['schedule']['cron']` `*/N` → `N/60` h; else default `1`.
- `startHour` / `endHour` ← best-effort parse of `config['time_window']` (extract the first two hour numbers, honoring "вечера"/"дня" → +12 when < 12 and a "до …вечера" phrasing is present); if not parseable, default `8..22`.
- `message` ← `fallbackMessage` (the agent description) — chosen explicitly (Vasily, 2026-06-30): the wizard has no message field, so the voice utterance is the honest notification text. No desktop builder change in this increment.

**Validation rules (boundary, clamp — never reject):** `intervalHours` → `[0.25, 24]`; `startHour` → `[0,23]`; `endHour` → `[startHour+1, 24]`; empty/whitespace `message` → `"Напоминание"`. The Dart interval/time parsers live here (or a small sibling `ru_interval_parse.dart`) and are pure + unit-tested against the same strings `_parse_interval_hours` handles.

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

**DST policy (explicit, so tests are deterministic):** fire times are naive **local** wall-clock `DateTime`s built by hour arithmetic; the gateway resolves them to `TZDateTime` via `tz.local`. We do **not** special-case DST — on a spring-forward day a non-existent local hour resolves per the `timezone` library's normalization, and a fall-back hour may map once; a ±1h drift on the two transition days a year is accepted for reminders (documented, not "fixed"). Tests inject a fixed `from` in a fixed zone, so they never depend on the host clock or zone.

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
Deterministic id scheme so re-sync cleanly replaces an agent's pending notifications. Concrete math: `base = (stableHash(agentName) & 0x7FFF) << 8` (a 256-slot block per agent; max id `0x7FFF00` ≈ 8.39M, well within int32), fire-slot `id = base + slotIndex`, `slotIndex ∈ [0, 255]` and always ≥ the per-agent fire budget. `cancelForAgent` cancels `base..base+255`. Residual risk stated honestly: the 15-bit name hash can collide at hundreds of distinct agent names (birthday bound) — acceptable for a phone (a user won't hold thousands of reminder agents); if two names collide, re-sync simply reschedules both into the shared block, never crashes.

### 3.4 `reminder_scheduler.dart`
```dart
class ReminderScheduler {
  Future<void> syncAll(DateTime now);          // import / resume / toggle
  Future<void> setEnabled(String agent, bool); // toggle → persist + sync
  Future<void> snooze(String agent, Duration); // persist snoozeUntil + sync
}
```
`syncAll` (explicit two-pass over **all** stored agents, so stale notifications can never leak):
1. **Budget pass:** count enabled reminder agents `K`; `perAgentBudget = K == 0 ? 0 : max(1, GLOBAL_PENDING_BUDGET ~/ K)` where `GLOBAL_PENDING_BUDGET = 56` (headroom under the iOS hard cap of 64 across the whole app — see §5).
2. **Per-agent pass:** for **every** stored agent — if `template == 'reminder' && enabled` → `cancelForAgent` then `scheduleAt(...)` for `nextFireTimes(from: max(now, snoozeUntil), horizonEnd: now + 7d, maxCount: perAgentBudget)`; **else** (disabled, or non-reminder, or null template) → `cancelForAgent` only. Cancelling the non-scheduled set is what makes a toggle-off (or an agent that stopped being a reminder) actually clear its OS notifications.

Idempotent: cancel-then-reschedule on every resume yields the same pending set. The global-budget split is deterministic, so the `reminder_scheduler` tests assert exact counts.

### 3.5 Extensions to existing Increment-1 units (surgical)
- **`imported_agent.dart`** — add `String? template`, `Map<String, dynamic>? config`, `bool enabled` (default `true`), `DateTime? snoozeUntil`. `toJson/fromJson` stay backward-compatible (Increment-1 records have no template → `template == null` → conversational-only, unchanged behaviour; `fromJson` already coalesces missing keys defensively). Immutable + a `copyWith` for enabled/snooze updates. (Intentional divergence from desktop, noted for a future reconciliation: desktop keeps snooze in a separate `snooze.json`; mobile keeps `snoozeUntil` on the agent record — simpler, no parity assumed.)
- **`bundle_importer.dart`** — after locating SKILL.md, if a `skill.yaml` (or `<name>/skill.yaml`) entry exists, parse `template` + `config` from it (add the pure-Dart `yaml` package — the current flat `_frontmatter` parser cannot read nested `config:`). Keep the importer pure (decode only). A missing/malformed `skill.yaml` must **not** fail the import — the agent still imports as conversational-only. **Note:** for a voice-built skill the SKILL.md is *synthetic* ([`publisher._synthesize_skill_md`](../../../kernel/skills/publisher.py) — body is just `# {name}\n\n{description}`); the real config lives in the co-bundled `skill.yaml` and `manifest.yaml`, and the description (= raw voice utterance) is the only human text, which is exactly why it becomes the reminder message (§3.1).
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
- The pending-notification horizon is bounded (iOS caps total pending at **64** across the whole app, **not** per agent) → a single global budget `GLOBAL_PENDING_BUDGET = 56` is split across all enabled reminder agents (§3.4), and each schedules ~7 days ahead within its share; topped up on each app open.
- **Honest UX disclaimer:** if the app is not opened for longer than the scheduled horizon, the queue runs dry until next open (a rare case). We say this rather than imply infinite background.
- Notification permission denied → the agent still imports; its toggle shows "нужно разрешение на уведомления" and routes to settings. No silent failure.

## 6. Error handling (honest, never crash)
| Failure | Behavior |
|---|---|
| Bundle has no `skill.yaml` (Increment-1 / a SKILL.md skill) | `template == null` → conversational-only, no scheduling (backward compatible). |
| `skill.yaml` with `template != reminder` | Stored, not scheduled; UI is honest ("этот агент пока только беседует"). |
| Malformed `config` (hours/interval out of range) | Clamped to safe defaults + honest note; never crashes the import or sync. |
| Unparseable `interval` / `time_window` free-text | `intervalHours` → 1, window → 8..22 (honest defaults); reminder still fires. |
| Malformed / unparseable `skill.yaml` | Ignored; agent imports as conversational-only (import never fails on it). |
| Toggle off / agent ceases to be a reminder | `syncAll` cancel-pass clears its OS notifications (no stale fires). |
| > `GLOBAL_PENDING_BUDGET` worth of agents | Per-agent budget shrinks deterministically (≥1 each); the soonest fires are kept first. |
| Notification permission denied | Imports; toggle shows "нужно разрешение" → settings route. |
| Horizon exhausted (app unopened > horizon) | Re-topped-up on next open; UX disclaimer sets the expectation. |

## 7. Anti-pivot ✓
Reminders run **only on the phone** — local notifications, local file store, zero KALI server, zero LLM in the execution path. This makes "your data and your agents stay on your phone" literally true and is honestly disclosable. It strengthens exactly the moat axes competitors leave unoccupied (voice-created agent + mobile + UGC + local data), and adds no dev-integration / OS-assistant / crypto surface.

## 8. Testing (`flutter test` via `C:\src\flutter\flutter\bin\flutter.bat`)
- **`reminder_schedule` (pure, the core):** fires at `start_hour` then every `interval`; stops at `end_hour`; rolls to the next day; respects `maxCount` + `horizonEnd`; boundary hours (start==end-1, interval > window); snooze applied via `from`. Many deterministic cases — clock injected.
- **`reminder_config` (the **real** shape):** `intervalHours` from nested `config['reminders']['interval_hours']`; free-text `config['interval']` ("каждые 2 часа" / "каждый час" / "раз в 30 минут") → hours/fraction via the Dart port; `config['time_window']` ("с 8 до 22" / "с 8 утра до 10 вечера" / "утром") → start/end or 8..22 default; **message falls back to the description**; out-of-range/non-numeric/empty inputs clamp, never throw.
- **`bundle_importer`:** a **real** voice-built reminder bundle → `template=='reminder'` + populated nested `config`; a SKILL.md-only bundle → `template==null` (back-compat preserved); a bundle with a corrupt `skill.yaml` → still imports conversational-only.
- **`agent_store`:** round-trips `template`/`config`/`enabled`/`snoozeUntil`; old (Increment-1) JSON without the new keys still loads.
- **`reminder_scheduler` (fake gateway):** `syncAll` registers the schedule-function's times; `setEnabled(false)` → `cancelForAgent`; `snooze` shifts the first fire; a non-reminder/disabled agent schedules nothing **and is cancel-passed**; the **global 56-budget split** across K enabled agents yields the asserted per-agent counts; re-`syncAll` is idempotent (cancel-then-reschedule).
- **Widget:** "Мои агенты" shows a reminder row with toggle + next-fire; permission-denied state renders the honest prompt.
- **Live (deferred — Vasily, real device `kali_test_34`):** import a real shared reminder → grant permission → a real notification fires at the scheduled time with the app backgrounded/killed.

## 9. Grounding items for the implementer
1. **Round-trip a real bundle.** Export a voice-built reminder from the desktop and confirm its `.tar.gz` carries `skill.yaml` with `template: reminder` + a populated `config` (high confidence from [`kernel/skill_executor.py`](../../../kernel/skill_executor.py) `TEMPLATE_REGISTRY` + [`kernel/skills/publisher.py`](../../../kernel/skills/publisher.py) `_add_bundle_members`, which adds `manifest.yaml`+`skill.yaml` for voice-built skills — but verify on a real artifact before relying on it).
2. **New dependencies:** `flutter_local_notifications`, `timezone`, `yaml`. Confirm they are absent from `mobile/pubspec.yaml`; the native config (iOS permissions/`AppDelegate`, Android `AndroidManifest` receivers + `POST_NOTIFICATIONS` on API 33+) is an honest, separate setup step — call it out in the plan.
3. **Notification id scheme** + `timezone` init (`tz.initializeTimeZones()` + set `tz.local`) before any `zonedSchedule`.
4. **Snooze as a notification action** needs a native background-action handler. If that proves heavy, the plan may degrade snooze to an **in-app** snooze button (tapping the notification opens the agent) and defer the on-notification action — note the chosen path explicitly.
5. **Config key names (RESOLVED — see §3.1).** Grounded against the producer, not `reminder.py`: a voice-built reminder `config:` is the **nested wizard dict** — `interval` (free-text), `time_window` (free-text), and `reminders: {enabled, interval_hours}` (or top-level `schedule.cron` for sub-hour) injected by `skill_generator._with_schedule`. There is **no** `message`/`start_hour`/`end_hour` key. `parseReminderConfig` must follow the §3.1 precedence and port `_parse_interval_hours`/`_parse_interval_minutes`; verify against a real exported artifact (item 1).
6. **DST:** the `timezone` package's local-time normalization governs the two transition days; the §3.2 policy accepts the ±1h drift rather than special-casing it — keep `nextFireTimes` naive-local and resolve in the gateway.
