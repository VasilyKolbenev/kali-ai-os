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
}
