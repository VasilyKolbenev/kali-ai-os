import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'config.dart';
import 'token_store.dart';

/// App-wide in-memory token cache, hydrated from secure storage on startup and
/// updated by the deep-link pairing handler. Read synchronously by the Dio
/// interceptor and the WebSocket client.
final tokenHolderProvider = Provider<TokenHolder>((ref) => TokenHolder());

/// Shared Dio instance with proper timeouts for all API calls.
///
/// Installs [KaliTokenInterceptor] so every request presents `X-KALI-Token`
/// when a token is available (LAN auth for the Rust control plane).
///
/// Usage: `final dio = ref.read(dioProvider);`
final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
    sendTimeout: const Duration(seconds: 15),
  ));
  dio.interceptors.add(KaliTokenInterceptor(ref.read(tokenHolderProvider)));
  return dio;
});

/// Builds a full API URL from the stored server IP.
/// Returns null if not connected.
String? apiUrl(String path, WidgetRef ref) {
  final ip = ref.read(serverIpProvider);
  if (ip == null) return null;
  return ServerConfig.api(ip, path);
}
