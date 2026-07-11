import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/profile_store.dart';
import 'package:kali_mobile/standalone/user_profile.dart';

void main() {
  late Directory tmp;
  setUp(() async => tmp = await Directory.systemTemp.createTemp('profile_store'));
  tearDown(() async => tmp.delete(recursive: true));

  test('round-trips a saved profile', () async {
    final store = FileProfileStore(baseDir: tmp);
    await store.save(const UserProfile(
      name: 'Вася',
      gender: 'female',
      occupation: 'врач',
      city: 'Ереван',
      ageRange: '26-35',
    ));
    final loaded = await FileProfileStore(baseDir: tmp).load();
    expect(loaded.name, 'Вася');
    expect(loaded.gender, 'female');
    expect(loaded.city, 'Ереван');
  });

  test('load returns empty profile when file absent', () async {
    final p = await FileProfileStore(baseDir: tmp).load();
    expect(p.isEmpty, isTrue);
  });

  test('corrupt JSON yields empty profile, not a crash', () async {
    await File('${tmp.path}/profile.json').writeAsString('{');
    final p = await FileProfileStore(baseDir: tmp).load();
    expect(p.isEmpty, isTrue);
  });
}
