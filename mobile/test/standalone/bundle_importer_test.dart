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

/// Build a payload where SKILL.md content is raw bytes (for non-UTF8 testing).
String _payloadRawSkill(String archiveName, List<int> skillBytes) {
  final archive = Archive()
    ..addFile(ArchiveFile('$archiveName/SKILL.md', skillBytes.length, skillBytes));
  final gz = GZipEncoder().encode(TarEncoder().encode(archive));
  return base64Url.encode(gz).replaceAll('=', '');
}

/// Build a payload with a symlink entry.
String _payloadWithSymlink(String name, String skillMd, String symlinkName, String symlinkTarget) {
  final archive = Archive();
  final bytes = utf8.encode(skillMd);
  archive.addFile(ArchiveFile('$name/SKILL.md', bytes.length, bytes));
  archive.addFile(ArchiveFile.symlink(symlinkName, symlinkTarget));
  final tar = TarEncoder().encode(archive);
  final gz = GZipEncoder().encode(tar);
  return base64Url.encode(gz).replaceAll('=', '');
}

void main() {
  // ── Existing tests ──────────────────────────────────────────────────────────

  test('imports name+description+body from SKILL.md frontmatter', () async {
    const md = '---\nname: chef\ndescription: помощник по рецептам\n---\nТы — повар.';
    final a = await importBundle(_payload('chef', md));
    expect(a.name, 'chef');
    expect(a.description, 'помощник по рецептам');
    expect(a.skillMd.contains('Ты — повар.'), isTrue);
  });

  test('rejects a zip-slip path', () async {
    const md = '---\nname: chef\ndescription: x\n---\nbody';
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
    const md = '---\nname: ab\ndescription: y\n---\nb';
    final a = await importBundle(_payload('ab', md));
    expect(a.name, 'ab');
  });

  // ── Fix 1: name validation at importer boundary ─────────────────────────────

  test('rejects hostile path-traversal name (../../evil)', () async {
    const md = '---\nname: ../../evil\ndescription: x\n---\nbody';
    expect(
      () => importBundle(_payload('agent', md)),
      throwsA(
        isA<BundleImportError>().having(
          (e) => e.message,
          'message',
          contains('safe identifier'),
        ),
      ),
    );
  });

  test('rejects name with slash (a/b)', () async {
    const md = '---\nname: a/b\ndescription: x\n---\nbody';
    expect(
      () => importBundle(_payload('agent', md)),
      throwsA(isA<BundleImportError>()),
    );
  });

  test('rejects name with uppercase (UPPER)', () async {
    const md = '---\nname: UPPER\ndescription: x\n---\nbody';
    expect(
      () => importBundle(_payload('agent', md)),
      throwsA(isA<BundleImportError>()),
    );
  });

  // ── Fix 2: backslash path rejection ─────────────────────────────────────────

  test('rejects a bundle entry with a backslash path', () async {
    const md = '---\nname: chef\ndescription: x\n---\nbody';
    expect(
      () => importBundle(_payload('chef', md, extraPaths: ['dir\\evil.sh'])),
      throwsA(isA<BundleImportError>()),
    );
  });

  // ── Fix 2: symlink rejection ─────────────────────────────────────────────────

  test('rejects a bundle that contains a symlink entry', () async {
    const md = '---\nname: chef\ndescription: x\n---\nbody';
    expect(
      () => importBundle(_payloadWithSymlink('chef', md, 'chef/link', '/etc/passwd')),
      throwsA(
        isA<BundleImportError>().having(
          (e) => e.message,
          'message',
          contains('symlink'),
        ),
      ),
    );
  });

  // ── Fix 4: malformed UTF-8 becomes BundleImportError ─────────────────────────

  test('rejects a SKILL.md with invalid UTF-8 as BundleImportError, not FormatException',
      () async {
    // 0xFF 0xFE is invalid UTF-8 (BOM-like but not a valid UTF-8 sequence)
    final badUtf8 = [0xFF, 0xFE, 0x00];
    // Must throw BundleImportError (not leak a raw FormatException)
    await expectLater(
      () => importBundle(_payloadRawSkill('agent', badUtf8)),
      throwsA(isA<BundleImportError>()),
    );
  });
}
