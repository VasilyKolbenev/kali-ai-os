import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'imported_agent.dart';

/// Local persistence of imported agents (one JSON file per agent).
abstract class AgentStore {
  /// Persists [agent], overwriting any existing entry with the same name.
  Future<void> save(ImportedAgent agent);

  /// Returns all stored agents (order unspecified).
  Future<List<ImportedAgent>> list();

  /// Returns the agent named [name], or `null` if none is stored.
  Future<ImportedAgent?> get(String name);

  /// Removes the agent named [name] (no-op if absent).
  Future<void> delete(String name);
}

/// Agent names accepted by the export gate: lowercase latin, digits, hyphen.
final RegExp _safeName = RegExp(r'^[a-z0-9-]+$');

/// File-backed [AgentStore] writing `<baseDir>/<name>.json`.
///
/// In production [baseDir] is `null` and resolves lazily to
/// `getApplicationDocumentsDirectory()/kali_agents/`. Unit tests inject a temp
/// [Directory] so no native `path_provider` channel is touched.
class FileAgentStore implements AgentStore {
  FileAgentStore({Directory? baseDir}) : _baseDir = baseDir;

  Directory? _baseDir;

  Future<Directory> _dir() async {
    var dir = _baseDir;
    if (dir == null) {
      final docs = await getApplicationDocumentsDirectory();
      dir = Directory('${docs.path}/kali_agents');
      _baseDir = dir;
    }
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  File _fileFor(Directory dir, String name) => File('${dir.path}/$name.json');

  void _checkName(String name) {
    if (!_safeName.hasMatch(name)) {
      throw ArgumentError.value(name, 'name', 'unsafe agent name');
    }
  }

  @override
  Future<void> save(ImportedAgent agent) async {
    _checkName(agent.name);
    final dir = await _dir();
    await _fileFor(dir, agent.name).writeAsString(jsonEncode(agent.toJson()));
  }

  @override
  Future<List<ImportedAgent>> list() async {
    final dir = await _dir();
    final out = <ImportedAgent>[];
    await for (final entity in dir.list()) {
      if (entity is File && entity.path.endsWith('.json')) {
        final json = jsonDecode(await entity.readAsString()) as Map<String, dynamic>;
        out.add(ImportedAgent.fromJson(json));
      }
    }
    return out;
  }

  @override
  Future<ImportedAgent?> get(String name) async {
    _checkName(name);
    final dir = await _dir();
    final file = _fileFor(dir, name);
    if (!await file.exists()) return null;
    final json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    return ImportedAgent.fromJson(json);
  }

  @override
  Future<void> delete(String name) async {
    _checkName(name);
    final dir = await _dir();
    final file = _fileFor(dir, name);
    if (await file.exists()) {
      await file.delete();
    }
  }
}
