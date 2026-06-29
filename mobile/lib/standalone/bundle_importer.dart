import 'dart:convert';

import 'package:archive/archive.dart';

import 'imported_agent.dart';

/// Raised when a `kali://import` payload cannot be safely turned into an agent.
class BundleImportError implements Exception {
  BundleImportError(this.message);

  final String message;

  @override
  String toString() => 'BundleImportError: $message';
}

/// Decode a `kali://import` `d=` payload (base64url, '='-stripped, of a .tar.gz)
/// into an [ImportedAgent]. Rejects path-traversal entries and a missing/invalid
/// SKILL.md. Pure: no I/O beyond decoding.
Future<ImportedAgent> importBundle(String payload) async {
  final padded = payload + '=' * ((4 - payload.length % 4) % 4);
  final List<int> raw;
  try {
    raw = base64Url.decode(padded);
  } catch (_) {
    throw BundleImportError('payload is not valid base64url');
  }
  final Archive archive;
  try {
    archive = TarDecoder().decodeBytes(const GZipDecoder().decodeBytes(raw));
  } catch (_) {
    throw BundleImportError('payload is not a valid .tar.gz');
  }
  for (final f in archive.files) {
    if (f.name.contains('..') || f.name.startsWith('/') || f.name.contains(':')) {
      throw BundleImportError('unsafe path in bundle: ${f.name}');
    }
  }
  final skill = archive.files.firstWhere(
    (f) => f.isFile && (f.name == 'SKILL.md' || f.name.endsWith('/SKILL.md')),
    orElse: () => throw BundleImportError('bundle has no SKILL.md'),
  );
  final md = utf8.decode(skill.content as List<int>);
  final fm = _frontmatter(md);
  final name = fm['name']?.trim();
  if (name == null || name.isEmpty) {
    throw BundleImportError('SKILL.md missing name');
  }
  return ImportedAgent(
    name: name,
    description: (fm['description'] ?? '').trim(),
    skillMd: md,
    installedAt: DateTime.now().toUtc(),
  );
}

/// Parse the leading `---`-delimited YAML frontmatter into a flat string map.
/// Only `key: value` scalars are needed (name, description). Returns {} if none.
Map<String, String> _frontmatter(String md) {
  final lines = md.split('\n');
  if (lines.isEmpty || lines.first.trim() != '---') return <String, String>{};
  final out = <String, String>{};
  for (var i = 1; i < lines.length; i++) {
    if (lines[i].trim() == '---') break;
    final idx = lines[i].indexOf(':');
    if (idx > 0) {
      final k = lines[i].substring(0, idx).trim();
      var v = lines[i].substring(idx + 1).trim();
      if (v.length >= 2 &&
          ((v.startsWith('"') && v.endsWith('"')) ||
              (v.startsWith("'") && v.endsWith("'")))) {
        v = v.substring(1, v.length - 1);
      }
      out[k] = v;
    }
  }
  return out;
}
