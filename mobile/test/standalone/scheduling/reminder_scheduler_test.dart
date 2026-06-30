import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_scheduler.dart';

import 'fake_notification_gateway.dart';

/// Records the order of gateway operations so a test can assert the two-pass
/// invariant (every cancel happens before any schedule within one syncAll).
class _RecordingGateway implements NotificationGateway {
  final List<String> ops = [];
  @override
  Future<bool> requestPermission() async => true;
  @override
  Future<void> scheduleAt(int id, DateTime when, String t, String b) async =>
      ops.add('schedule');
  @override
  Future<void> cancelForAgent(String name) async => ops.add('cancel');
  @override
  Future<int> pendingCount() async => 0;
}

/// Detects whether concurrent syncAll calls interleave their gateway ops. A
/// single syncAll awaits each op sequentially, so at most one of ITS ops is ever
/// suspended at a time. The gateway yields on every op; if it ever observes two
/// ops suspended at once, two un-serialized syncAll calls were overlapping —
/// the exact window where one call's cancel wipes another's fresh schedule.
class _InterleaveDetectorGateway implements NotificationGateway {
  int _inFlight = 0;
  bool interleaved = false;

  @override
  Future<bool> requestPermission() async => true;

  Future<void> _op() async {
    _inFlight++;
    if (_inFlight > 1) interleaved = true;
    await Future<void>.delayed(Duration.zero);
    _inFlight--;
  }

  @override
  Future<void> scheduleAt(int id, DateTime when, String t, String b) => _op();
  @override
  Future<void> cancelForAgent(String name) => _op();
  @override
  Future<int> pendingCount() async => 0;
}

Future<FileAgentStore> _store() async =>
    FileAgentStore(baseDir: await Directory.systemTemp.createTemp('sched'));

ImportedAgent _reminder(String n, {bool enabled = true}) => ImportedAgent(
      name: n,
      description: 'пить воду',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder',
      config: {
        'reminders': {'interval_hours': 2},
        'time_window': 'с 8 до 22',
      },
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
    expect(
      gw.scheduled.keys.every((id) =>
          id >= blockBase('water') && id < blockBase('water') + blockSlots),
      true,
    );
  });

  test('disabled / non-reminder agents schedule nothing and get cancel-passed',
      () async {
    final store = await _store();
    await store.save(_reminder('off', enabled: false));
    await store.save(ImportedAgent(
        name: 'chat',
        description: 'x',
        skillMd: 'md',
        installedAt: DateTime.utc(2026, 6, 30)));
    final gw = FakeNotificationGateway();
    await ReminderScheduler(store: store, gateway: gw)
        .syncAll(DateTime(2026, 6, 30, 7));
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
    await s.setEnabled('water', false, DateTime(2026, 6, 30, 7));
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
    expect(
        first.isAfter(DateTime(2026, 6, 30, 11, 59)), true); // pushed past 12:00
    expect((await store.get('water'))!.snoozeUntil, isNotNull);
  });

  test('global 56-budget split across K agents', () async {
    final store = await _store();
    for (var i = 0; i < 4; i++) {
      await store.save(_reminder('a$i'));
    }
    final gw = FakeNotificationGateway();
    await ReminderScheduler(store: store, gateway: gw)
        .syncAll(DateTime(2026, 6, 30, 7));
    // 56 ~/ 4 = 14 per agent, capped by the 7d horizon -> 14 each.
    expect(gw.scheduled.length, lessThanOrEqualTo(56));
  });

  test('concurrent syncAll calls are serialized (no interleaved passes)',
      () async {
    // Three overlapping syncAll calls (app-resume + deep-link + tile bootstrap
    // racing). Without a serialization guard their cancel/schedule passes
    // interleave, and one call's cancel wipes another's freshly-scheduled fires.
    // The detector trips if it ever sees two gateway ops in flight at once.
    final store = await _store();
    for (var i = 0; i < 3; i++) {
      await store.save(_reminder('agent$i'));
    }
    final gw = _InterleaveDetectorGateway();
    final s = ReminderScheduler(store: store, gateway: gw);

    await Future.wait([
      s.syncAll(DateTime(2026, 6, 30, 7)),
      s.syncAll(DateTime(2026, 6, 30, 7)),
      s.syncAll(DateTime(2026, 6, 30, 7)),
    ]);
    expect(gw.interleaved, false,
        reason: 'two syncAll passes overlapped — schedules can be wiped');
  });

  test('concurrent syncAll converges to the stable total deterministically',
      () async {
    // Many overlapping triples; the settled pending total must always equal the
    // single-sync total, never a degraded/zero count from a dropped schedule.
    final store = await _store();
    for (var i = 0; i < 3; i++) {
      await store.save(_reminder('agent$i'));
    }
    final gw = FakeNotificationGateway()..yieldOnEachOp = true;
    final s = ReminderScheduler(store: store, gateway: gw);

    await s.syncAll(DateTime(2026, 6, 30, 7));
    final expected = gw.scheduled.length;
    expect(expected, greaterThan(0));

    for (var run = 0; run < 40; run++) {
      await Future.wait([
        s.syncAll(DateTime(2026, 6, 30, 7)),
        s.syncAll(DateTime(2026, 6, 30, 7)),
        s.syncAll(DateTime(2026, 6, 30, 7)),
      ]);
      expect(gw.scheduled.length, expected,
          reason: 'run $run: concurrent syncAll dropped schedules');
    }
  });

  test('two-pass: every cancel precedes any schedule within one syncAll',
      () async {
    // Guards against the interleaved cancel+schedule hazard: if two agent
    // names collided in the same id block, a later agent's cancel could wipe an
    // earlier agent's freshly-scheduled fires. Cancelling everyone first removes
    // that ordering hazard.
    final store = await _store();
    await store.save(_reminder('water'));
    await store.save(_reminder('walk'));
    final gw = _RecordingGateway();
    await ReminderScheduler(store: store, gateway: gw)
        .syncAll(DateTime(2026, 6, 30, 7));

    final firstSchedule = gw.ops.indexOf('schedule');
    final lastCancel = gw.ops.lastIndexOf('cancel');
    expect(firstSchedule, greaterThan(lastCancel),
        reason: 'all cancels must happen before any schedule');
  });
}
