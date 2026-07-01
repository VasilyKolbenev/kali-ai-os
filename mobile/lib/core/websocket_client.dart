import 'dart:convert';
import 'dart:developer';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'config.dart';
import 'http_client.dart';
import 'token_store.dart';

final wsClientProvider = Provider(
  (ref) => WebSocketClient(tokenHolder: ref.read(tokenHolderProvider)),
);

/// Returns a log-safe rendering of [wsUrl] with any `token` query value
/// replaced by `token=***`.
///
/// The LAN pairing token is the control-plane security boundary — it must never
/// reach logs (dart:developer `log`, `debugPrint`, crash reports). This strips
/// the value while keeping the host/port/path visible for diagnostics. Pure so
/// it can be unit-tested. Falls back to a scheme+authority-only string if the
/// input can't be parsed as a URI.
String redactWsUrl(String wsUrl) {
  final uri = Uri.tryParse(wsUrl);
  if (uri == null) return wsUrl;
  if (!uri.queryParameters.containsKey('token')) return wsUrl;
  final query = uri.queryParameters.entries
      .map((e) => e.key == 'token' ? 'token=***' : '${e.key}=${e.value}')
      .join('&');
  return uri.replace(query: query).toString();
}

class WebSocketClient {
  WebSocketClient({TokenHolder? tokenHolder}) : _tokenHolder = tokenHolder;

  final TokenHolder? _tokenHolder;
  WebSocketChannel? _channel;
  Function(Map<String, dynamic>)? onMessage;
  String? _serverIp;
  int _reconnectAttempts = 0;

  bool get isConnected => _channel != null;

  /// Opens a WebSocket to the Desktop KALI (Rust proxy on port 3006).
  ///
  /// Awaits the real handshake ([WebSocketChannel.ready]) with a 5s timeout so
  /// callers learn whether the server is actually reachable.
  ///
  /// Returns `true` on a confirmed connection, `false` otherwise.
  Future<bool> connect(String ipAddress) async {
    // Already connected to the same address — nothing to do.
    if (_channel != null && _serverIp == ipAddress) return true;
    // Connected to a different address — drop the old socket first.
    if (_channel != null) {
      _channel!.sink.close();
      _channel = null;
    }

    _serverIp = ipAddress;

    // Default to port 3006 for Desktop KALI (Rust proxy). When paired, the
    // token rides as a `?token=` query param (ws can't send headers).
    final wsUrl = Uri.parse(ServerConfig.ws(ipAddress, token: _tokenHolder?.token));

    try {
      final channel = WebSocketChannel.connect(wsUrl);
      // Wait for the actual handshake before reporting success.
      await channel.ready.timeout(const Duration(seconds: 5));
      _channel = channel;
      _channel!.stream.listen(
        (message) {
          if (onMessage != null) {
            try {
              final decoded = jsonDecode(message as String);
              onMessage!(decoded);
            } catch (e) {
              log("Failed to decode WS message: $e", name: 'WebSocketClient');
            }
          }
        },
        onDone: () {
          log("WS Disconnected", name: 'WebSocketClient');
          _channel = null;
          _scheduleReconnect();
        },
        onError: (error) {
          log("WS Error: $error", name: 'WebSocketClient');
          _channel = null;
          _scheduleReconnect();
        },
      );
      // Never log the tokenized URL — the token is the LAN-security boundary.
      log("WS Connected to $ipAddress:${ServerConfig.port}",
          name: 'WebSocketClient');
      _reconnectAttempts = 0; // reset on successful connection
      return true;
    } catch (e) {
      log("WS Connection failed: $e", name: 'WebSocketClient');
      _channel = null;
      _scheduleReconnect();
      return false;
    }
  }

  void _scheduleReconnect() {
    if (_serverIp == null) return;
    
    // Exponential backoff: 1s, 2s, 4s, 8s, max 10s.
    final delay = (1 << _reconnectAttempts).clamp(1, 10);
    log("Scheduling WS reconnect in $delay seconds...", name: 'WebSocketClient');
    
    Future.delayed(Duration(seconds: delay), () async {
      if (_serverIp != null && _channel == null) {
        _reconnectAttempts++;
        await connect(_serverIp!);
      }
    });
  }

  void send(String type, Map<String, dynamic> data) {
    if (_channel == null) return;
    
    final payload = jsonEncode({
      'type': type,
      'data': data,
    });
    
    _channel!.sink.add(payload);
  }

  void disconnect() {
    _serverIp = null;
    _channel?.sink.close();
    _channel = null;
  }
}
