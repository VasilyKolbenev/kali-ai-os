import 'dart:convert';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/bundle_importer.dart';

/// Build a base64url(.tar.gz) payload with [skillMd] under `<name>/SKILL.md`.
String _payload(String name, String skillMd, {List<String> extraPaths = const []}) {
  final archive = Archive();
  final bytes = utf8.encode(skillMd);
  archive.addFile(ArchiveFile('$name/SKILL.md', bytes.length, bytes));
  for (final p in extraPaths) {
    archive.addFile(ArchiveFile(p, 1, [0]));
  }
  final tar = TarEncoder().encode(archive);
  final gz = GZipEncoder().encode(tar); // archive v4: non-nullable List<int>
  return base64Url.encode(gz).replaceAll('=', ''); // mirror producer stripping '='
}

void main() {
  test('imports name+description+body from SKILL.md frontmatter', () async {
    final md = '---\nname: chef\ndescription: помощник по рецептам\n---\nТы — повар.';
    final a = await importBundle(_payload('chef', md));
    expect(a.name, 'chef');
    expect(a.description, 'помощник по рецептам');
    expect(a.skillMd.contains('Ты — повар.'), isTrue);
  });

  test('rejects a zip-slip path', () async {
    final md = '---\nname: chef\ndescription: x\n---\nbody';
    expect(
      () => importBundle(_payload('chef', md, extraPaths: ['../evil.sh'])),
      throwsA(isA<BundleImportError>()),
    );
  });

  test('rejects a bundle with no SKILL.md', () async {
    final archive = Archive()
      ..addFile(ArchiveFile('chef/notes.txt', 3, utf8.encode('abc')));
    final gz = GZipEncoder().encode(TarEncoder().encode(archive));
    expect(
      () => importBundle(base64Url.encode(gz).replaceAll('=', '')),
      throwsA(isA<BundleImportError>()),
    );
  });

  test('restores stripped base64url padding', () async {
    final md = '---\nname: ab\ndescription: y\n---\nb';
    final a = await importBundle(_payload('ab', md));
    expect(a.name, 'ab');
  });
}
