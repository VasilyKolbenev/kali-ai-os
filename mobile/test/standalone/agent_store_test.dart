import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';
import 'package:kali_mobile/standalone/scheduling/notification_ids.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_scheduler.dart';

ImportedAgent _reminder(String name) => ImportedAgent(
      name: name,
      description: 'пить воду',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder',
      config: const {
        'reminders': {'interval_hours': 2},
      },
    );

void main() {
  test('save -> list -> get -> delete round-trip', () async {
    final dir = await Directory.systemTemp.createTemp('kali_agents_test');
    final store = FileAgentStore(baseDir: dir);
    final a = ImportedAgent(
      name: 'chef',
      description: 'повар',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 29),
    );
    await store.save(a);
    expect((await store.list()).single.name, 'chef');
    expect((await store.get('chef'))!.description, 'повар');
    await store.delete('chef');
    expect(await store.list(), isEmpty);
  });

  test('rejects an unsafe agent name', () async {
    final dir = await Directory.systemTemp.createTemp('kali_agents_test');
    final store = FileAgentStore(baseDir: dir);
    final a = ImportedAgent(
      name: '../evil',
      description: 'x',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 29),
    );
    expect(() => store.save(a), throwsArgumentError);
  });

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

  test('list() skips corrupt + missing-name files, returns only valid agents',
      () async {
    final dir = await Directory.systemTemp.createTemp('kali_agents_test');
    final store = FileAgentStore(baseDir: dir);
    await store.save(_reminder('water'));
    await store.save(ImportedAgent(
      name: 'chef',
      description: 'повар',
      skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 29),
    ));
    // A truncated JSON file and a valid-JSON-but-missing-name file.
    await File('${dir.path}/broken.json').writeAsString('{');
    await File('${dir.path}/noname.json')
        .writeAsString('{"description":"x","skillMd":"md","installedAt":'
            '"2026-06-29T00:00:00.000Z"}');

    final List<ImportedAgent> agents = await store.list();
    expect(agents.map((a) => a.name).toSet(), {'water', 'chef'});
  });

  test('syncAll over a store with a corrupt file still schedules the valid '
      'reminder', () async {
    final dir = await Directory.systemTemp.createTemp('kali_agents_test');
    final store = FileAgentStore(baseDir: dir);
    await store.save(_reminder('water'));
    await File('${dir.path}/broken.json').writeAsString('{');

    final gw = _RecordingGateway();
    final scheduler = ReminderScheduler(store: store, gateway: gw);
    await scheduler.syncAll(DateTime.utc(2026, 6, 30, 8));

    expect(gw.scheduled, isNotEmpty,
        reason: 'a corrupt sibling file must not block scheduling');
  });

  test('save is atomic — no .tmp file remains after a successful write',
      () async {
    final dir = await Directory.systemTemp.createTemp('kali_agents_test');
    final store = FileAgentStore(baseDir: dir);
    await store.save(_reminder('water'));

    final tmps = dir
        .listSync()
        .whereType<File>()
        .where((f) => f.path.endsWith('.tmp'))
        .toList();
    expect(tmps, isEmpty, reason: 'temp file must be renamed away');
    expect((await store.get('water'))!.name, 'water');
  });
}

/// Minimal in-memory gateway: records scheduled ids so a sync can be asserted.
class _RecordingGateway implements NotificationGateway {
  final Map<int, DateTime> scheduled = <int, DateTime>{};

  @override
  Future<bool> requestPermission() async => true;

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
