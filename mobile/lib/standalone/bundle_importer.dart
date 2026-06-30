import 'dart:convert';

import 'package:archive/archive.dart';

import 'imported_agent.dart';
import 'safe_name.dart';

/// Raised when a `kali://import` payload cannot be safely turned into an agent.
class BundleImportError implements Exception {
  BundleImportError(this.message);

  final String message;

  @override
  String toString() => 'BundleImportError: $message';
}

/// Maximum inflated tar size accepted (10 MB). Protects against decompression bombs.
const int _kMaxInflatedBytes = 10 * 1024 * 1024;

/// Decode a `kali://import` `d=` payload (base64url, '='-stripped, of a .tar.gz)
/// into an [ImportedAgent]. Rejects path-traversal entries, symlink entries,
/// backslash paths, decompression bombs, non-UTF-8 SKILL.md, and invalid names.
/// Pure: no I/O beyond decoding.
Future<ImportedAgent> importBundle(String payload) async {
  // Fix: base64url decode
  final padded = payload + '=' * ((4 - payload.length % 4) % 4);
  final List<int> raw;
  try {
    raw = base64Url.decode(padded);
  } catch (_) {
    throw BundleImportError('payload is not valid base64url');
  }

  // Fix 3: decompress, then cap inflated size to guard against decompression bombs
  final List<int> inflated;
  try {
    inflated = const GZipDecoder().decodeBytes(raw);
  } catch (_) {
    throw BundleImportError('payload is not a valid .tar.gz');
  }
  if (inflated.length > _kMaxInflatedBytes) {
    throw BundleImportError('bundle too large');
  }

  final Archive archive;
  try {
    archive = TarDecoder().decodeBytes(inflated);
  } catch (_) {
    throw BundleImportError('payload is not a valid .tar.gz');
  }

  // Fix 2: zip-slip guard — reject path-traversal, absolute paths, colons,
  // backslash separators, and symlink entries
  for (final f in archive.files) {
    if (f.isSymbolicLink) {
      throw BundleImportError('symlink entries are not allowed');
    }
    if (f.name.contains('..') ||
        f.name.startsWith('/') ||
        f.name.contains(':') ||
        f.name.contains('\\')) {
      throw BundleImportError('unsafe path in bundle: ${f.name}');
    }
  }

  final skill = archive.files.firstWhere(
    (f) => f.isFile && (f.name == 'SKILL.md' || f.name.endsWith('/SKILL.md')),
    orElse: () => throw BundleImportError('bundle has no SKILL.md'),
  );

  // Fix 4: wrap UTF-8 decode so FormatException becomes BundleImportError
  final String md;
  try {
    md = utf8.decode(skill.content as List<int>);
  } on FormatException {
    throw BundleImportError('SKILL.md is not valid UTF-8');
  }

  final fm = _frontmatter(md);
  final name = fm['name']?.trim();
  if (name == null || name.isEmpty) {
    throw BundleImportError('SKILL.md missing name');
  }

  // Fix 1: validate name at the importer boundary using shared allowlist
  if (!kSafeAgentName.hasMatch(name)) {
    throw BundleImportError('SKILL.md name is not a safe identifier');
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
