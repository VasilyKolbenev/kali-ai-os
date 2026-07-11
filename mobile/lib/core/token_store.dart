import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Storage key for the control-plane token (one per install).
const String kControlPlaneTokenKey = 'kali_control_plane_token';

/// HTTP header the Rust control plane accepts for LAN auth.
const String kaliTokenHeader = 'X-KALI-Token';

/// Android secure-storage options that force AES-backed
/// `EncryptedSharedPreferences` instead of the legacy (deprecated) keystore
/// path. minSdk 24 supports it. Shared by all `FlutterSecureStorage` users so
/// the LLM key and the pairing token are always encrypted at rest.
const AndroidOptions kaliAndroidSecureStorage =
    AndroidOptions(encryptedSharedPreferences: true);

/// Minimal key/value contract so [TokenStore] can be unit-tested with an
/// in-memory fake instead of the real platform keystore.
abstract class TokenKeyValueStore {
  Future<void> write(String key, String value);
  Future<String?> read(String key);
  Future<void> delete(String key);
}

/// Adapts [FlutterSecureStorage] to [TokenKeyValueStore].
class SecureTokenKeyValueStore implements TokenKeyValueStore {
  const SecureTokenKeyValueStore([
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

/// Persists the control-plane token in OS-backed secure storage.
///
/// Inject a [TokenKeyValueStore] to test without hitting real secure storage.
class TokenStore {
  TokenStore({TokenKeyValueStore? storage})
      : _storage = storage ?? const SecureTokenKeyValueStore();

  final TokenKeyValueStore _storage;

  /// Persists [token] under [kControlPlaneTokenKey].
  Future<void> saveToken(String token) =>
      _storage.write(kControlPlaneTokenKey, token);

  /// Reads the persisted token, or `null` if none is stored.
  Future<String?> readToken() => _storage.read(kControlPlaneTokenKey);

  /// Removes any persisted token.
  Future<void> clearToken() => _storage.delete(kControlPlaneTokenKey);
}

/// In-memory cache of the current token, read synchronously by the Dio
/// interceptor at request time.
///
/// On startup, call [loadFromStore] to hydrate from secure storage. The
/// deep-link pairing handler (a later task) calls [set] so a freshly-scanned
/// token takes effect immediately, without an app restart.
class TokenHolder {
  TokenHolder({TokenStore? store}) : _store = store ?? TokenStore();

  final TokenStore _store;
  String? _token;

  /// Current token, or `null` if not yet paired.
  String? get token => _token;

  /// Updates the in-memory token. Pass `null` to clear it.
  void set(String? token) => _token = token;

  /// Hydrates the in-memory cache from persisted secure storage.
  Future<void> loadFromStore() async {
    _token = await _store.readToken();
  }
}

/// Dio interceptor that presents [kaliTokenHeader] on every request when the
/// [TokenHolder] holds a token, and omits it otherwise.
class KaliTokenInterceptor extends Interceptor {
  KaliTokenInterceptor(this._holder);

  final TokenHolder _holder;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final token = _holder.token;
    if (token != null && token.isNotEmpty) {
      options.headers[kaliTokenHeader] = token;
    }
    handler.next(options);
  }
}
