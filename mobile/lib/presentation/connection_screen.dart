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
  final TextEditingController _ipController = TextEditingController(text: '10.0.2.2');
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
      wsClient.connect(ip);
      
      // Give it a moment to connect
      await Future.delayed(const Duration(milliseconds: 500));
      
      if (wsClient.isConnected && mounted) {
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
                  errorText: _error,
                  border: const OutlineInputBorder(),
                  filled: true,
                  fillColor: const Color(0xFF16161B),
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
              
              const SizedBox(height: 32),
              
              // Helpful tip for normal users
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppTheme.cardColor,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: AppTheme.primary.withValues(alpha: 0.15)),
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
