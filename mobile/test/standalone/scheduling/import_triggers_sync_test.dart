import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/core/deep_link_service.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_scheduler.dart';

import 'fake_notification_gateway.dart';

Future<FileAgentStore> _store() async =>
    FileAgentStore(baseDir: await Directory.systemTemp.createTemp('import'));

ImportedAgent _reminder(String n) => ImportedAgent(
      name: n,
      description: 'пить воду',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder',
      config: {
        'reminders': {'interval_hours': 2},
        'time_window': 'с 8 до 22',
      },
    );

void main() {
  test('importing a reminder then syncing schedules it', () async {
    final store = await _store();
    await store.save(_reminder('water'));
    final gw = FakeNotificationGateway();
    await ReminderScheduler(store: store, gateway: gw)
        .syncAll(DateTime(2026, 6, 30, 7));
    expect(gw.scheduled, isNotEmpty);
  });

  test('scheduleImportedReminder requests permission + syncs a reminder',
      () async {
    final store = await _store();
    final agent = _reminder('water');
    await store.save(agent);
    final gw = FakeNotificationGateway();
    final scheduler = ReminderScheduler(store: store, gateway: gw);
    await scheduleImportedReminder(
      agent,
      scheduler: scheduler,
      gateway: gw,
      now: DateTime(2026, 6, 30, 7),
    );
    expect(gw.scheduled, isNotEmpty);
  });

  test('scheduleImportedReminder is a no-op for conversational agents',
      () async {
    final store = await _store();
    final agent = ImportedAgent(
      name: 'chef',
      description: 'повар',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
    );
    await store.save(agent);
    final gw = FakeNotificationGateway();
    final scheduler = ReminderScheduler(store: store, gateway: gw);
    await scheduleImportedReminder(
      agent,
      scheduler: scheduler,
      gateway: gw,
      now: DateTime(2026, 6, 30, 7),
    );
    expect(gw.scheduled, isEmpty);
  });
}
