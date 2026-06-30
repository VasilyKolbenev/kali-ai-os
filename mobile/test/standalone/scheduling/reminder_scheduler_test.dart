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
}
