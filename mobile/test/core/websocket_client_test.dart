// Unit tests for the WS log-redaction seam (never log the LAN pairing token).
//
// [redactWsUrl] is the pure helper the connect path uses so the tokenized WS
// URL never reaches logs. We assert the token value is stripped for tokened
// URLs and that untokened / unparseable inputs pass through unchanged.

import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/config.dart';
import 'package:kali_mobile/core/websocket_client.dart';

void main() {
  group('redactWsUrl', () {
    test('strips the token value, keeping host/port/path visible', () {
      const token = 'SECRET-TOKEN-123';
      final url = ServerConfig.ws('192.168.1.50', token: token);

      final redacted = redactWsUrl(url);

      expect(redacted, isNot(contains(token)));
      expect(redacted, contains('192.168.1.50:3006/ws'));
      expect(redacted, contains('token=***'));
    });

    test('strips a url-encoded token value', () {
      const token = 'a b/c+d';
      final url = ServerConfig.ws('10.0.2.2', token: token);

      final redacted = redactWsUrl(url);

      // Neither the raw nor the percent-encoded token may survive.
      expect(redacted, isNot(contains('a b/c+d')));
      expect(redacted, isNot(contains('a%20b%2Fc%2Bd')));
      expect(redacted, contains('token=***'));
    });

    test('leaves an untokened URL unchanged', () {
      final url = ServerConfig.ws('192.168.1.50');
      expect(redactWsUrl(url), url);
    });
  });

  group('isCleartextTargetAllowed', () {
    test('allows cleartext ws to a LAN 192.168.x.x host', () {
      expect(isCleartextTargetAllowed(ServerConfig.ws('192.168.1.50')), isTrue);
    });

    test('allows cleartext ws to the emulator host bridge and loopback', () {
      expect(isCleartextTargetAllowed(ServerConfig.ws('10.0.2.2')), isTrue);
      expect(isCleartextTargetAllowed(ServerConfig.ws('127.0.0.1')), isTrue);
    });

    test('rejects cleartext ws to a public host', () {
      expect(isCleartextTargetAllowed('ws://93.184.216.34:3006/ws'), isFalse);
      expect(isCleartextTargetAllowed('ws://relay.kali.app/ws'), isFalse);
    });

    test('rejects cleartext http to a public/cloud host', () {
      expect(isCleartextTargetAllowed('http://api.kali.app/v1'), isFalse);
    });

    test('requires https/wss for a cloud endpoint', () {
      // A cloud endpoint is only allowed over TLS, regardless of host.
      expect(isCleartextTargetAllowed('https://api.kali.app/v1'), isTrue);
      expect(isCleartextTargetAllowed('wss://relay.kali.app/ws'), isTrue);
    });

    test('rejects octal/hex-looking octets that a resolver could widen', () {
      // 010.x parses as 8.x (public) in a libc resolver — must be rejected.
      expect(isCleartextTargetAllowed('ws://010.0.0.1:3006/ws'), isFalse);
    });
  });
}
