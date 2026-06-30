import 'package:kali_mobile/standalone/agent_store.dart';

import 'notification_gateway.dart';
import 'notification_ids.dart';
import 'reminder_config.dart';
import 'reminder_schedule.dart';

/// Total notifications we will ever keep pending across all reminder agents.
/// Keeps us well under the iOS 64-pending cap (room for other notifications).
const int kGlobalPendingBudget = 56;

const Duration _kHorizon = Duration(days: 7);

/// Syncs all enabled reminder agents to the OS via [gateway]. Idempotent:
/// cancel-then-reschedule on every call (import / app-resume / toggle / snooze).
class ReminderScheduler {
  /// Creates a scheduler over an agent [store] and notification [gateway].
  ReminderScheduler({required this.store, required this.gateway});

  /// Source of imported agents (reads config / enabled / snooze).
  final AgentStore store;

  /// Target the fire times are registered with.
  final NotificationGateway gateway;

  /// Cancels every stored agent's block, then reschedules enabled reminders.
  ///
  /// Two-pass to guarantee stale ids are cleared even for agents that became
  /// disabled / non-reminder since the last sync. [now] is injected so callers
  /// (and tests) control the clock; production callers pass `DateTime.now()`.
  Future<void> syncAll(DateTime now) async {
    final agents = await store.list();
    final active =
        agents.where((a) => a.template == 'reminder' && a.enabled).toList();

    // Honest upper edge: cap the active set to the soonest GLOBAL budget.
    final capped = active.length > kGlobalPendingBudget
        ? (active..sort((a, b) => a.name.compareTo(b.name)))
            .sublist(0, kGlobalPendingBudget)
        : active;
    final k = capped.length;
    final perAgent = k == 0 ? 0 : (kGlobalPendingBudget ~/ k).clamp(1, blockSlots);
    final cappedNames = capped.map((a) => a.name).toSet();

    for (final a in agents) {
      await gateway.cancelForAgent(a.name); // clears stale ids for everyone
      if (!cappedNames.contains(a.name)) continue;
      final cfg =
          parseReminderConfig(a.config ?? const {}, fallbackMessage: a.description);
      final from = (a.snoozeUntil != null && a.snoozeUntil!.isAfter(now))
          ? a.snoozeUntil!
          : now;
      final times = nextFireTimes(
        config: cfg,
        from: from,
        horizonEnd: now.add(_kHorizon),
        maxCount: perAgent,
      );
      for (var i = 0; i < times.length; i++) {
        await gateway.scheduleAt(slotId(a.name, i), times[i], a.name, cfg.message);
      }
    }
  }

  /// Toggles [agentName] on/off and re-syncs. [now] defaults to wall-clock.
  Future<void> setEnabled(String agentName, bool enabled, [DateTime? now]) async {
    final a = await store.get(agentName);
    if (a == null) return;
    await store.save(a.copyWith(enabled: enabled));
    await syncAll(now ?? DateTime.now());
  }

  /// Suppresses [agentName] for [d] from now and re-syncs. [now] for tests.
  Future<void> snooze(String agentName, Duration d, [DateTime? now]) async {
    final clock = now ?? DateTime.now();
    final a = await store.get(agentName);
    if (a == null) return;
    await store.save(a.copyWith(snoozeUntil: clock.add(d)));
    await syncAll(clock);
  }
}
