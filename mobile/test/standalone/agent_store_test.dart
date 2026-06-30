import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';

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
}
