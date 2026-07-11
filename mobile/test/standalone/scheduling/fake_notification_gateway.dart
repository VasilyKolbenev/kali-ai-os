import 'dart:math';

import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';

/// In-memory [NotificationGateway] for scheduler tests: records scheduled
/// (id → fire time) entries and honours per-agent block cancellation.
class FakeNotificationGateway implements NotificationGateway {
  /// Currently scheduled notifications keyed by notification id.
  final Map<int, DateTime> scheduled = <int, DateTime>{};

  /// Value returned by [requestPermission]; flip to simulate a denial.
  bool permission = true;

  /// Whether [requestPermission] has been called (consent-gating assertions).
  bool permissionRequested = false;

  /// Number of times [requestPermission] was called.
  int permissionRequestCount = 0;

  /// Per-agent count of [cancelForAgent] invocations (perf assertions).
  final Map<String, int> cancelCounts = <String, int>{};

  /// When true, every gateway op yields to the event queue for a small random
  /// delay before touching state. Forces concurrent [syncAll] calls to
  /// genuinely cross their cancel/schedule passes (a cancel from one call can
  /// land after another call's schedule) — exposes any missing serialization
  /// guard, which a fixed `Duration.zero` lockstep would not.
  bool yieldOnEachOp = false;

  final Random _rng = Random(1234);

  Future<void> _maybeYield() async {
    if (yieldOnEachOp) {
      await Future<void>.delayed(Duration(microseconds: _rng.nextInt(3)));
    }
  }

  @override
  Future<bool> requestPermission() async {
    permissionRequested = true;
    permissionRequestCount++;
    return permission;
  }

  @override
  Future<void> scheduleAt(int id, DateTime when, String t, String b) async {
    await _maybeYield();
    scheduled[id] = when;
  }

  @override
  Future<void> cancelForAgent(String name) async {
    await _maybeYield();
    cancelCounts[name] = (cancelCounts[name] ?? 0) + 1;
    final int base = blockBase(name);
    scheduled.removeWhere((id, _) => id >= base && id < base + blockSlots);
  }

  @override
  Future<int> pendingCount() async => scheduled.length;
}
