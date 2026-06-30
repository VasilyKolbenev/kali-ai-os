// Tests for the standalone deep-link import seam.
//
// `_handleImport` routes a `kali://import` to either the on-device importer
// (standalone / no desktop) or the desktop server. That decision + the
// on-device import action are extracted into pure, injectable functions so they
// can be tested without a Navigator, secure storage, or the network.

import 'dart:convert';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/deep_link_service.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';

/// In-memory [AgentStore] that records saves.
class _FakeStore implements AgentStore {
  final List<ImportedAgent> saved = [];

  @override
  Future<void> save(ImportedAgent agent) async => saved.add(agent);

  @override
  Future<List<ImportedAgent>> list() async => List.of(saved);

  @override
  Future<ImportedAgent?> get(String name) async {
    for (final a in saved) {
      if (a.name == name) return a;
    }
    return null;
  }

  @override
  Future<void> delete(String name) async =>
      saved.removeWhere((a) => a.name == name);
}

String _payload(String name, String skillMd) {
  final archive = Archive();
  final bytes = utf8.encode(skillMd);
  archive.addFile(ArchiveFile('$name/SKILL.md', bytes.length, bytes));
  final gz = GZipEncoder().encode(TarEncoder().encode(archive));
  return base64Url.encode(gz).replaceAll('=', '');
}

void main() {
  group('shouldImportOnDevice', () {
    test('no desktop paired → on-device', () {
      expect(shouldImportOnDevice(standaloneMode: false, serverIp: null), isTrue);
    });

    test('standalone mode → on-device even if an ip lingers', () {
      expect(shouldImportOnDevice(standaloneMode: true, serverIp: '10.0.2.2'), isTrue);
    });

    test('paired desktop, not standalone → server path', () {
      expect(shouldImportOnDevice(standaloneMode: false, serverIp: '10.0.2.2'), isFalse);
    });
  });

  group('importOnDevice', () {
    test('imports the bundle and saves it to the store', () async {
      final store = _FakeStore();
      const md = '---\nname: chef\ndescription: повар\n---\nТы — повар.';

      final agent = await importOnDevice(_payload('chef', md), store: store);

      expect(agent.name, 'chef');
      expect(store.saved.single.name, 'chef');
      expect(store.saved.single.description, 'повар');
    });

    test('propagates BundleImportError without saving', () async {
      final store = _FakeStore();
      // Not a valid base64url/.tar.gz payload.
      await expectLater(
        () => importOnDevice('not-a-bundle!!!', store: store),
        throwsA(isA<Object>()),
      );
      expect(store.saved, isEmpty);
    });
  });
}
