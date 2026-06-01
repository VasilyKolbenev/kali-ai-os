import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'config.dart';

/// Shared Dio instance with proper timeouts for all API calls.
/// Usage: `final dio = ref.read(dioProvider);`
final dioProvider = Provider<Dio>((ref) {
  return Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
    sendTimeout: const Duration(seconds: 15),
  ));
});

/// Builds a full API URL from the stored server IP.
/// Returns null if not connected.
String? apiUrl(String path, WidgetRef ref) {
  final ip = ref.read(serverIpProvider);
  if (ip == null) return null;
  return 'http://$ip:3006$path';
}
