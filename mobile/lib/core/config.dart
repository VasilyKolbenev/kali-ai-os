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
  ///
  /// Dart's `web_socket_channel` cannot send headers, so when a control-plane
  /// [token] is present it rides as a URL-encoded `?token=` query param (the
  /// Rust `/ws` route accepts it for the upgrade). Omitted when [token] is null.
  static String ws(String ip, {String? token}) {
    final base = 'ws://$ip:$port/ws';
    if (token == null || token.isEmpty) return base;
    return '$base?token=${Uri.encodeComponent(token)}';
  }
}
