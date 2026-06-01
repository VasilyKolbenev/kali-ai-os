import 'dart:convert';
import 'dart:developer';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

final wsClientProvider = Provider((ref) => WebSocketClient());

class WebSocketClient {
  WebSocketChannel? _channel;
  Function(Map<String, dynamic>)? onMessage;
  String? _serverIp;
  int _reconnectAttempts = 0;

  bool get isConnected => _channel != null;

  void connect(String ipAddress) {
    if (_channel != null) return;
    
    _serverIp = ipAddress;
    
    // Default to port 3006 for Desktop KALI (Rust proxy)
    final wsUrl = Uri.parse('ws://$ipAddress:3006/ws');
    
    try {
      _channel = WebSocketChannel.connect(wsUrl);
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
      log("WS Connected to $wsUrl", name: 'WebSocketClient');
      _reconnectAttempts = 0; // reset on successful connection
    } catch (e) {
      log("WS Connection failed: $e", name: 'WebSocketClient');
      _channel = null;
      _scheduleReconnect();
      rethrow;
    }
  }

  void _scheduleReconnect() {
    if (_serverIp == null) return;
    
    // Exponential backoff: 1s, 2s, 4s, 8s, max 10s.
    final delay = (1 << _reconnectAttempts).clamp(1, 10);
    log("Scheduling WS reconnect in $delay seconds...", name: 'WebSocketClient');
    
    Future.delayed(Duration(seconds: delay), () {
      if (_serverIp != null && _channel == null) {
        _reconnectAttempts++;
        connect(_serverIp!);
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
