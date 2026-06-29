import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../core/websocket_client.dart';
import '../core/config.dart';
import '../core/l10n.dart';
import '../core/theme.dart';
import 'main_screen.dart';

class ConnectionScreen extends ConsumerStatefulWidget {
  const ConnectionScreen({super.key});

  @override
  ConsumerState<ConnectionScreen> createState() => _ConnectionScreenState();
}

class _ConnectionScreenState extends ConsumerState<ConnectionScreen> {
  // Prefill the emulator loopback only in debug; on a real phone the user
  // enters their Desktop's LAN IP (e.g. 192.168.x.x).
  final TextEditingController _ipController =
      TextEditingController(text: kDebugMode ? '10.0.2.2' : '');
  bool _isConnecting = false;
  String? _error;

  @override
  void dispose() {
    _ipController.dispose();
    super.dispose();
  }

  void _connect() async {
    setState(() {
      _isConnecting = true;
      _error = null;
    });

    final wsClient = ref.read(wsClientProvider);
    final ip = _ipController.text.trim();
    ref.read(serverIpProvider.notifier).state = ip;

    try {
      final connected = await wsClient.connect(ip);

      if (!mounted) return;
      if (connected) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const MainScreen()),
        );
      } else {
        final t = L10n.of(ref);
        setState(() => _error = t.connectFailed(ip));
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _isConnecting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Logo / icon
              Container(
                padding: const EdgeInsets.all(24),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      AppTheme.primary.withValues(alpha: 0.2),
                      Colors.transparent,
                    ],
                  ),
                ),
                child: const Icon(Icons.wifi_tethering, size: 64, color: AppTheme.primary),
              ).animate().fadeIn(duration: 600.ms).scale(begin: const Offset(0.8, 0.8)),
              const SizedBox(height: 24),
              
              Text(
                t.connectTitle,
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white),
              ).animate().fadeIn(delay: 200.ms),
              const SizedBox(height: 12),
              
              Text(
                t.connectSubtitle,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 14, color: AppTheme.textSecondary, height: 1.5),
              ).animate().fadeIn(delay: 300.ms),
              const SizedBox(height: 32),
              
              TextField(
                controller: _ipController,
                decoration: InputDecoration(
                  labelText: t.connectHint,
                  labelStyle: const TextStyle(color: AppTheme.textSecondary),
                  hintText: '192.168.x.x',
                  hintStyle: const TextStyle(color: AppTheme.textDim),
                  errorText: _error,
                  border: const OutlineInputBorder(),
                  filled: true,
                  fillColor: AppTheme.glassSurface,
                  prefixIcon: const Icon(Icons.computer, color: AppTheme.textSecondary),
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(color: Colors.white, fontSize: 18, letterSpacing: 1),
              ).animate().fadeIn(delay: 400.ms),
              const SizedBox(height: 24),
              
              SizedBox(
                width: double.infinity,
                height: 54,
                child: ElevatedButton(
                  onPressed: _isConnecting ? null : _connect,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.primary,
                    foregroundColor: Colors.black,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    elevation: 4,
                  ),
                  child: _isConnecting 
                    ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                    : Text(t.connectButton, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                ),
              ).animate().fadeIn(delay: 500.ms),
              
              const SizedBox(height: 16),

              // QR pairing hint for non-tech users on a token-enforced LAN
              Row(
                children: [
                  Icon(Icons.qr_code_scanner, color: AppTheme.primary.withValues(alpha: 0.7), size: 18),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      t.connectQrHint,
                      style: TextStyle(color: AppTheme.textSecondary, fontSize: 12, height: 1.4),
                    ),
                  ),
                ],
              ).animate().fadeIn(delay: 600.ms),
              const SizedBox(height: 24),

              // Helpful tip for normal users
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppTheme.glassSurface,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: AppTheme.glassBorder),
                ),
                child: Row(
                  children: [
                    Icon(Icons.lightbulb_outline, color: AppTheme.primary.withValues(alpha: 0.7), size: 22),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Text(
                        t.connectTip,
                        style: TextStyle(color: AppTheme.textSecondary, fontSize: 13, height: 1.5),
                      ),
                    ),
                  ],
                ),
              ).animate().fadeIn(delay: 800.ms).slideY(begin: 0.3),
            ],
          ),
        ),
      ),
    );
  }
}
