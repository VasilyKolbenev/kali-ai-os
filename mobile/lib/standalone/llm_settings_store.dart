import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/token_store.dart' show kaliAndroidSecureStorage;
import 'llm_client.dart';

/// Secure-storage keys for the BYO-LLM settings.
const String kLlmProviderKey = 'kali_llm_provider';
const String kLlmApiKeyKey = 'kali_llm_api_key';

/// Minimal key/value contract so [LlmSettingsStore] can be unit-tested with an
/// in-memory fake instead of the real platform keystore. Mirrors
/// `TokenKeyValueStore` in `core/token_store.dart`.
abstract class LlmKeyValueStore {
  Future<void> write(String key, String value);
  Future<String?> read(String key);
  Future<void> delete(String key);
}

/// Adapts [FlutterSecureStorage] to [LlmKeyValueStore].
class SecureLlmKeyValueStore implements LlmKeyValueStore {
  const SecureLlmKeyValueStore([
    this._storage = const FlutterSecureStorage(
      aOptions: kaliAndroidSecureStorage,
    ),
  ]);

  final FlutterSecureStorage _storage;

  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

/// An immutable [LlmSettings] snapshot loaded from persistent storage. Suitable
/// to inject directly into [LlmClient].
class StoredLlmSettings implements LlmSettings {
  const StoredLlmSettings({required this.provider, required this.apiKey});

  @override
  final LlmProvider provider;

  @override
  final String? apiKey;
}

/// Persists the chosen [LlmProvider] + API key in OS-backed secure storage.
///
/// Inject an [LlmKeyValueStore] to test without hitting real secure storage.
class LlmSettingsStore {
  LlmSettingsStore({LlmKeyValueStore? storage})
      : _storage = storage ?? const SecureLlmKeyValueStore();

  final LlmKeyValueStore _storage;

  /// Persists the provider choice.
  Future<void> setProvider(LlmProvider provider) =>
      _storage.write(kLlmProviderKey, provider.name);

  /// Reads the persisted provider, defaulting to [LlmProvider.anthropic].
  Future<LlmProvider> readProvider() async {
    final raw = await _storage.read(kLlmProviderKey);
    return LlmProvider.values.firstWhere(
      (p) => p.name == raw,
      orElse: () => LlmProvider.anthropic,
    );
  }

  /// Persists the API key.
  Future<void> setApiKey(String apiKey) =>
      _storage.write(kLlmApiKeyKey, apiKey);

  /// Reads the persisted API key, or `null` if none is stored.
  Future<String?> readApiKey() => _storage.read(kLlmApiKeyKey);

  /// Clears the stored API key.
  Future<void> clearApiKey() => _storage.delete(kLlmApiKeyKey);

  /// Loads a snapshot suitable to inject into [LlmClient].
  Future<StoredLlmSettings> load() async => StoredLlmSettings(
        provider: await readProvider(),
        apiKey: await readApiKey(),
      );
}
