import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';

void main() {
  test('round-trips through json', () {
    final a = ImportedAgent(
      name: 'chef',
      description: 'повар',
      skillMd: '# chef\n...',
      installedAt: DateTime.utc(2026, 6, 29),
    );
    final back = ImportedAgent.fromJson(a.toJson());
    expect(back.name, 'chef');
    expect(back.description, 'повар');
    expect(back.skillMd, '# chef\n...');
    expect(back.installedAt, a.installedAt);
  });

  test('new fields round-trip + copyWith', () {
    final a = ImportedAgent(
      name: 'water', description: 'пить воду', skillMd: 'md',
      installedAt: DateTime.utc(2026, 6, 30),
      template: 'reminder', config: {'interval': 'каждые 2 часа'},
      enabled: true, snoozeUntil: DateTime.utc(2026, 6, 30, 12),
    );
    final back = ImportedAgent.fromJson(a.toJson());
    expect(back.template, 'reminder');
    expect(back.config!['interval'], 'каждые 2 часа');
    expect(back.enabled, true);
    expect(back.snoozeUntil, DateTime.utc(2026, 6, 30, 12));
    expect(a.copyWith(enabled: false).enabled, false);
  });
  test('back-compat: Increment-1 JSON (no new keys) loads', () {
    final back = ImportedAgent.fromJson({
      'name': 'chef', 'description': 'повар', 'skillMd': 'md',
      'installedAt': '2026-06-29T00:00:00.000Z',
    });
    expect(back.template, isNull);
    expect(back.enabled, true);       // defaults on
    expect(back.snoozeUntil, isNull);
  });
}
