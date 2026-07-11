// Verifies both secure stores force Android EncryptedSharedPreferences.
//
// The pairing token (core/token_store.dart) and the BYO-LLM API key
// (standalone/llm_settings_store.dart) live in FlutterSecureStorage. On Android
// the default path is the deprecated keystore; we must opt into AES-backed
// EncryptedSharedPreferences. Both stores share the const
// [kaliAndroidSecureStorage]; here we assert that const carries the flag and
// that a FlutterSecureStorage built from it reports it via toMap().

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/token_store.dart';

void main() {
  group('kaliAndroidSecureStorage', () {
    test('enables EncryptedSharedPreferences', () {
      expect(
        kaliAndroidSecureStorage.toMap()['encryptedSharedPreferences'],
        'true',
      );
    });

    test('a FlutterSecureStorage built from it carries the option', () {
      const storage =
          FlutterSecureStorage(aOptions: kaliAndroidSecureStorage);
      expect(
        storage.aOptions.toMap()['encryptedSharedPreferences'],
        'true',
      );
    });
  });
}
