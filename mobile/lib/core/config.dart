import 'package:flutter_riverpod/flutter_riverpod.dart';

final serverIpProvider = StateProvider<String?>((ref) => null);

/// Single source of truth for how the app reaches the KALI backend.
///
/// Today the backend is the Desktop KALI on the LAN (Rust proxy on port 3006),
/// addressed by [serverIpProvider]. Centralizing the scheme/port/URL builders
/// here makes the eventual LAN→cloud/relay switch a one-place change instead of
/// a grep-and-edit across every screen.
class ServerConfig {
  ServerConfig._();

  /// Port of the Desktop KALI Rust proxy.
  static const int port = 3006;

  /// HTTP base URL for the given server [ip] (no trailing slash).
  static String httpBase(String ip) => 'http://$ip:$port';

  /// Builds a full HTTP API URL for [path] (which must start with `/`).
  static String api(String ip, String path) => '${httpBase(ip)}$path';

  /// WebSocket URL for the live event channel.
  static String ws(String ip) => 'ws://$ip:$port/ws';
}
