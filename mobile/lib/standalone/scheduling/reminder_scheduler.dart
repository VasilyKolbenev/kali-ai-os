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

  /// The tail of the serialized sync chain, or null when idle. Each [syncAll]
  /// chains onto this so cancel-then-schedule passes never interleave (an
  /// interleaved cancel would wipe another call's freshly-scheduled fires —
  /// see [_syncAllOnce]).
  Future<void>? _running;

  /// The single coalesced follow-up Future, or null when none is queued. A 2nd
  /// concurrent call queues it; a 3rd+ joins the same one (the OS state only
  /// needs ONE re-sync of the latest store snapshot once the in-flight drains).
  Future<void>? _pending;

  /// `now` captured for the queued follow-up; refreshed by each call that joins
  /// it so the follow-up runs against the latest clock.
  DateTime? _pendingNow;

  /// Serialized entry point: at most one sync runs at a time, with at most one
  /// coalesced follow-up. Callers get a Future that completes once a sync that
  /// reflects (at least) their request has finished. [now] is injected so
  /// callers/tests control the clock; production callers pass `DateTime.now()`.
  Future<void> syncAll(DateTime now) {
    final running = _running;
    if (running == null) {
      return _running = _run(now);
    }
    // A sync is in flight. Join (or create) the single follow-up; refresh its
    // clock so it reflects the latest request.
    _pendingNow = now;
    return _pending ??= running.then((_) {
      final at = _pendingNow ?? now;
      _pending = null;
      _pendingNow = null;
      return _running = _run(at);
    });
  }

  Future<void> _run(DateTime now) async {
    try {
      await _syncAllOnce(now);
    } finally {
      // Mark idle iff no follow-up is queued. A queued follow-up will have
      // re-armed _running via its `.then` continuation before any new call can
      // observe idle, so we never clear a live follow-up.
      if (_pending == null) _running = null;
    }
  }

  /// Cancels every stored agent's block, then reschedules enabled reminders.
  ///
  /// Two-pass to guarantee stale ids are cleared even for agents that became
  /// disabled / non-reminder since the last sync. [now] is injected so callers
  /// (and tests) control the clock; production callers pass `DateTime.now()`.
  Future<void> _syncAllOnce(DateTime now) async {
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

    // Pass 1 — cancel EVERY stored agent's block first. This must complete
    // before any scheduling: two agent names can hash to the same id block
    // (the 15-bit collision the id scheme tolerates), so an interleaved
    // cancel+schedule would let a later agent's cancel wipe an earlier agent's
    // freshly-scheduled fires within the same sync.
    for (final a in agents) {
      await gateway.cancelForAgent(a.name);
    }

    // Pass 2 — schedule the capped, enabled reminders.
    for (final a in capped) {
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
