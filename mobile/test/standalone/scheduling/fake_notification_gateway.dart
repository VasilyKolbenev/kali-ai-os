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

  @override
  Future<bool> requestPermission() async {
    permissionRequested = true;
    return permission;
  }

  @override
  Future<void> scheduleAt(int id, DateTime when, String t, String b) async =>
      scheduled[id] = when;

  @override
  Future<void> cancelForAgent(String name) async {
    final int base = blockBase(name);
    scheduled.removeWhere((id, _) => id >= base && id < base + blockSlots);
  }

  @override
  Future<int> pendingCount() async => scheduled.length;
}
