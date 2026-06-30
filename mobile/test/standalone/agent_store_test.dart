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
}
