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
}
