// Unit tests for the control-plane token plumbing (mobile pairing-token, P1.1).
//
// Three testable seams, all isolated from native channels:
//   * [TokenStore] round-trips through an injected key/value store (here a
//     fake in-memory map — never real secure storage in a unit test).
//   * [TokenHolder] is the in-memory cache the Dio interceptor reads at request
//     time; a freshly-paired token set via [TokenHolder.set] takes effect with
//     no app restart.
//   * [KaliTokenInterceptor] adds `X-KALI-Token` only when a token is present.
//   * [ServerConfig.ws] appends a URL-encoded `?token=` only when present.

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/config.dart';
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
  group('TokenStore', () {
    test('save → read → clear round-trip', () async {
      final store = TokenStore(storage: _FakeKeyValueStore());

      expect(await store.readToken(), isNull);

      await store.saveToken('ABC123');
      expect(await store.readToken(), 'ABC123');

      await store.clearToken();
      expect(await store.readToken(), isNull);
    });
  });

  group('TokenHolder', () {
    test('starts empty and reflects a value set at runtime', () {
      final holder = TokenHolder();
      expect(holder.token, isNull);

      holder.set('FRESH');
      expect(holder.token, 'FRESH');

      holder.set(null);
      expect(holder.token, isNull);
    });

    test('loadFromStore populates the cache from persisted storage', () async {
      final store = TokenStore(storage: _FakeKeyValueStore());
      await store.saveToken('PERSISTED');

      final holder = TokenHolder(store: store);
      await holder.loadFromStore();

      expect(holder.token, 'PERSISTED');
    });
  });

  group('KaliTokenInterceptor', () {
    RequestOptions runOnRequest(TokenHolder holder) {
      final interceptor = KaliTokenInterceptor(holder);
      final options = RequestOptions(path: '/skills');
      // The handler's `next` just records that flow continued; we only assert
      // on the mutated options here.
      interceptor.onRequest(options, RequestInterceptorHandler());
      return options;
    }

    test('adds X-KALI-Token when the holder has a token', () {
      final holder = TokenHolder()..set('TOK');
      final options = runOnRequest(holder);
      expect(options.headers[kaliTokenHeader], 'TOK');
    });

    test('omits the header when the holder has no token', () {
      final holder = TokenHolder();
      final options = runOnRequest(holder);
      expect(options.headers.containsKey(kaliTokenHeader), isFalse);
    });
  });

  group('ServerConfig.ws', () {
    test('appends a url-encoded ?token= when present', () {
      expect(ServerConfig.ws('1.2.3.4', token: 'ABC'),
          'ws://1.2.3.4:3006/ws?token=ABC');
    });

    test('url-encodes reserved characters in the token', () {
      expect(ServerConfig.ws('1.2.3.4', token: 'a b/c+d'),
          'ws://1.2.3.4:3006/ws?token=a%20b%2Fc%2Bd');
    });

    test('omits the query param when no token', () {
      expect(ServerConfig.ws('1.2.3.4'), 'ws://1.2.3.4:3006/ws');
    });
  });
}
