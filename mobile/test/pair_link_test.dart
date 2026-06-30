// Unit tests for the `kali://pair` deep-link parsing + persist/hydrate seam
// (mobile pairing-token, P1.1, Task 2).
//
// The navigation side of the handler needs a live widget tree, so the pure
// parse logic is extracted into [parsePairLink] and the persist step into
// [applyPairing] — both testable without platform channels or a Navigator.

import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/deep_link_service.dart';
import 'package:kali_mobile/core/token_store.dart';

/// In-memory [TokenKeyValueStore] for tests — no platform channels.
class _FakeKeyValueStore implements TokenKeyValueStore {
  final Map<String, String> _data = <String, String>{};

  @override
  Future<void> write(String key, String value) async => _data[key] = value;

  @override
  Future<String?> read(String key) async => _data[key];

  @override
  Future<void> delete(String key) async => _data.remove(key);
}

void main() {
  group('parsePairLink', () {
    test('extracts ip + token from a kali://pair link', () {
      final info =
          parsePairLink(Uri.parse('kali://pair?ip=192.168.1.5:3006&token=ABC'));
      expect(info, isNotNull);
      expect(info!.ip, '192.168.1.5:3006');
      expect(info.token, 'ABC');
    });

    test('accepts an ip without an explicit port', () {
      final info =
          parsePairLink(Uri.parse('kali://pair?ip=192.168.1.5&token=XYZ'));
      expect(info, isNotNull);
      expect(info!.ip, '192.168.1.5');
      expect(info.token, 'XYZ');
    });

    test('rejects a link missing the token', () {
      expect(parsePairLink(Uri.parse('kali://pair?ip=192.168.1.5')), isNull);
    });

    test('rejects a link missing the ip', () {
      expect(parsePairLink(Uri.parse('kali://pair?token=ABC')), isNull);
    });

    test('rejects empty ip or token values', () {
      expect(parsePairLink(Uri.parse('kali://pair?ip=&token=ABC')), isNull);
      expect(parsePairLink(Uri.parse('kali://pair?ip=192.168.1.5&token=')),
          isNull);
    });

    test('rejects a malformed host', () {
      expect(parsePairLink(Uri.parse('kali://pair?ip=not a host&token=ABC')),
          isNull);
    });

    // Pairing is LAN-only by design (the token is the LAN-security boundary).
    // A public host or a DNS name in the link means an attacker is trying to
    // exfiltrate the token to a server they control — reject both.
    test('rejects a public IP host (token exfiltration)', () {
      expect(parsePairLink(Uri.parse('kali://pair?ip=1.2.3.4&token=x')), isNull);
      expect(
          parsePairLink(Uri.parse('kali://pair?ip=8.8.8.8:3006&token=x')),
          isNull);
    });

    test('rejects a non-literal DNS host', () {
      expect(
          parsePairLink(Uri.parse('kali://pair?ip=evil.com&token=x')), isNull);
      expect(
          parsePairLink(Uri.parse('kali://pair?ip=localhost&token=x')), isNull);
    });

    test('accepts private / loopback / CGNAT hosts', () {
      for (final ip in [
        '192.168.1.5',
        '10.0.2.2',
        '172.16.0.1',
        '127.0.0.1',
        '100.64.0.1',
      ]) {
        expect(parsePairLink(Uri.parse('kali://pair?ip=$ip&token=x')),
            isNotNull, reason: ip);
      }
    });

    test('ignores the import link (different host)', () {
      expect(parsePairLink(Uri.parse('kali://import?n=foo&d=bar')), isNull);
    });

    test('ignores a non-kali scheme', () {
      expect(parsePairLink(Uri.parse('https://example.com/pair?ip=1.2.3.4&token=ABC')),
          isNull);
    });
  });

  group('applyPairing', () {
    test('persists the token and updates the holder', () async {
      final store = TokenStore(storage: _FakeKeyValueStore());
      final holder = TokenHolder(store: store);
      const info = PairInfo(ip: '1.2.3.4:3006', token: 'TOK');

      await applyPairing(info, store: store, holder: holder);

      expect(await store.readToken(), 'TOK');
      expect(holder.token, 'TOK');
    });
  });

  group('startup hydration', () {
    test('a persisted token is present in the holder after loadFromStore',
        () async {
      final store = TokenStore(storage: _FakeKeyValueStore());
      await store.saveToken('PERSISTED');

      final holder = TokenHolder(store: store);
      await holder.loadFromStore();

      expect(holder.token, 'PERSISTED');
    });
  });
}
