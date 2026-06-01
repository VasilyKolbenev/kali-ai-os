import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../core/theme.dart';
import '../core/websocket_client.dart';
import '../core/audio_recorder_service.dart';
import '../core/audio_player_service.dart';
import '../core/l10n.dart';
import 'dart:ui';
import 'dart:math' as math;

class VoiceScreen extends ConsumerStatefulWidget {
  const VoiceScreen({super.key});

  @override
  ConsumerState<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends ConsumerState<VoiceScreen> with SingleTickerProviderStateMixin {
  String _voiceState = "idle";
  String _transcript = "";
  late AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);

    final wsClient = ref.read(wsClientProvider);
    final audioPlayer = ref.read(audioPlayerProvider);

    wsClient.onMessage = (data) {
      if (!mounted) return;
      
      setState(() {
        if (data['type'] == 'voice.state') {
          _voiceState = data['data']['state'];
        } else if (data['type'] == 'voice.transcript') {
          _transcript = data['data']['text'];
        } else if (data['type'] == 'voice.tts_chunk') {
          audioPlayer.queueAudioChunk(data['data']['audio']);
        }
      });
    };
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  void _toggleMic() async {
    final recorder = ref.read(audioRecorderProvider);
    if (_voiceState == "idle") {
      recorder.startRecording();
      ref.read(wsClientProvider).send('voice.state', {'state': 'listening'});
      setState(() => _voiceState = "listening");
    } else {
      await recorder.stopRecording();
      ref.read(audioPlayerProvider).stop();
      ref.read(wsClientProvider).send('voice.state', {'state': 'idle'});
      setState(() => _voiceState = "idle");
    }
  }

  Color _getStateColor() {
    switch (_voiceState) {
      case 'listening': return AppTheme.primary;
      case 'thinking': return AppTheme.accent;
      case 'speaking': return const Color(0xFF22C55E);
      default: return Colors.white38;
    }
  }

  String _getStateLabel(L10n t) {
    switch (_voiceState) {
      case 'listening': return t.voiceListening;
      case 'thinking': return t.voiceThinking;
      case 'speaking': return t.voiceSpeaking;
      default: return t.voiceIdle;
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);
    final stateColor = _getStateColor();
    final isIdle = _voiceState == "idle";

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Stack(
        children: [
          // Ambient dynamic background
          Positioned.fill(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 800),
              decoration: BoxDecoration(
                gradient: RadialGradient(
                  colors: [
                    stateColor.withValues(alpha: isIdle ? 0.05 : 0.25),
                    Colors.transparent,
                  ],
                  radius: isIdle ? 1.0 : 1.5,
                  center: Alignment.center,
                ),
              ),
            ),
          ),
          
          SafeArea(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Spacer(),
                
                // Voice Status Label
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                  decoration: BoxDecoration(
                    color: stateColor.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: stateColor.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    _getStateLabel(t),
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: stateColor,
                      letterSpacing: 4,
                      fontWeight: FontWeight.bold,
                      fontSize: 14,
                    ),
                  ),
                ).animate(target: isIdle ? 0 : 1).fadeIn().scale(),
                
                const SizedBox(height: 80),
                
                // Central Multi-layered Orb
                GestureDetector(
                  onTap: _toggleMic,
                  child: AnimatedBuilder(
                    animation: _pulseController,
                    builder: (context, child) {
                      final scale = isIdle ? 1.0 : 1.0 + (_pulseController.value * 0.2);
                      final glowRadius = isIdle ? 15.0 : 30.0 + (_pulseController.value * 50.0);
                      
                      return Center(
                        child: Transform.scale(
                          scale: scale,
                          child: Container(
                            width: 180,
                            height: 180,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: LinearGradient(
                                colors: [
                                  stateColor.withValues(alpha: isIdle ? 0.2 : 0.8),
                                  stateColor.withValues(alpha: isIdle ? 0.05 : 0.3),
                                ],
                                begin: Alignment.topLeft,
                                end: Alignment.bottomRight,
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: stateColor.withValues(alpha: isIdle ? 0.2 : 0.6),
                                  blurRadius: glowRadius,
                                  spreadRadius: glowRadius / 3,
                                ),
                                if (!isIdle)
                                  BoxShadow(
                                    color: stateColor.withValues(alpha: 0.3),
                                    blurRadius: glowRadius * 1.5,
                                    spreadRadius: glowRadius / 2,
                                  ),
                              ],
                              border: Border.all(
                                color: isIdle ? Colors.white24 : stateColor.withValues(alpha: 0.8), 
                                width: isIdle ? 1 : 2
                              ),
                            ),
                            child: ClipOval(
                              child: BackdropFilter(
                                filter: ImageFilter.blur(sigmaX: 8, sigmaY: 8),
                                child: Center(
                                  child: Icon(
                                    isIdle ? Icons.mic_none_rounded : Icons.mic_rounded,
                                    size: 64,
                                    color: isIdle ? Colors.white54 : Colors.white,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
                
                const SizedBox(height: 80),
                
                // Live Transcript
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 40),
                  child: Text(
                    _transcript.isEmpty 
                      ? (isIdle ? t.voiceTapHint : t.voiceListeningHint)
                      : _transcript,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.displayLarge?.copyWith(
                      fontSize: 22,
                      fontWeight: FontWeight.w400,
                      height: 1.4,
                      color: isIdle ? AppTheme.textSecondary : Colors.white,
                    ),
                  ),
                ).animate().fadeIn(duration: 800.ms),
                
                const SizedBox(height: 24),
                
                // Hint for new users
                if (isIdle)
                  Container(
                    margin: const EdgeInsets.symmetric(horizontal: 40),
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                    decoration: BoxDecoration(
                      color: AppTheme.cardColor,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: Colors.white.withValues(alpha: 0.05)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.lightbulb_outline, color: AppTheme.primary.withValues(alpha: 0.7), size: 18),
                        const SizedBox(width: 10),
                        Flexible(
                          child: Text(
                            t.voiceTryHint,
                            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              fontSize: 13,
                              color: AppTheme.textSecondary,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ).animate().fadeIn(delay: 1200.ms).slideY(begin: 0.3),
                
                const Spacer(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
