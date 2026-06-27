import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'dart:ui';
import '../core/config.dart';
import '../core/theme.dart';
import '../core/l10n.dart';
import '../core/http_client.dart';
import '../core/websocket_client.dart';
import 'connection_screen.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  bool _isLoading = true;
  String? _error;
  
  // Settings state
  String _llmProvider = 'ollama';
  String _sttProvider = 'whisper_local';
  String _ttsProvider = 'f5_tts';

  // Human-friendly provider names
  static const Map<String, String> _llmLabels = {
    'ollama': 'Ollama (\u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e)',  // Ollama (локально)
    'openai': 'OpenAI (ChatGPT)',
    'anthropic': 'Anthropic (Claude)',
    'google': 'Google (Gemini)',
    'deepseek': 'DeepSeek',
    'groq': 'Groq (Llama-3 fast)',
    'mistral': 'Mistral AI',
  };

  static const Map<String, String> _sttLabels = {
    'whisper_local': 'Whisper (\u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e)',  // Whisper (локально)
    'openai_whisper': 'OpenAI Whisper (\u043e\u0431\u043b\u0430\u043a\u043e)',  // OpenAI Whisper (облако)
  };

  static const Map<String, String> _ttsLabels = {
    'f5_tts': 'JARVIS (\u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e, GPU)',  // JARVIS (локально, GPU)
    'elevenlabs': 'ElevenLabs (\u043e\u0431\u043b\u0430\u043a\u043e)',  // ElevenLabs (облако)
    'openai': 'OpenAI TTS (\u043e\u0431\u043b\u0430\u043a\u043e)',  // OpenAI TTS (облако)
  };

  @override
  void initState() {
    super.initState();
    _fetchConfig();
  }

  Future<void> _fetchConfig() async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) {
      setState(() {
        _error = "not_connected";
        _isLoading = false;
      });
      return;
    }

    try {
      final response = await ref.read(dioProvider).get(ServerConfig.api(ip, '/config'));
      if (response.statusCode == 200) {
        final data = response.data;
        setState(() {
          final llm = data['llm'] ?? {};
          // If auto_route is false and cloud is not preferred, or if explicitly asked? 
          // For simplicity in mobile UI, we check if auto_route is false and we want local.
          // Let's just use cloud_provider if it's not ollama.
          // Wait, if user selects ollama, we can just say "ollama".
          if (llm['auto_route'] == false && llm['local_provider'] == 'ollama') {
              _llmProvider = 'ollama';
          } else {
              _llmProvider = llm['cloud_provider'] ?? 'anthropic';
          }
          _sttProvider = data['voice']['stt_provider'] ?? 'whisper_local';
          _ttsProvider = data['voice']['tts_provider'] ?? 'f5_tts';
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _saveConfig(String key, dynamic value, String category) async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) return;
    final t = L10n.of(ref);
    try {
      await ref.read(dioProvider).patch(
        ServerConfig.api(ip, '/config'),
        data: {
          category: {
            key: value
          }
        },
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(t.settingSaved)),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(t.saveFailed(e.toString()))),
        );
      }
    }
  }

  Widget _buildSectionHeader(String title, IconData icon, {int delay = 0}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 24.0, horizontal: 8.0).copyWith(bottom: 16),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppTheme.primary.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: AppTheme.primary, size: 20),
          ),
          const SizedBox(width: 16),
          Text(
            title.toUpperCase(),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: AppTheme.textDim,
              fontWeight: FontWeight.bold,
              letterSpacing: 1.5,
            ),
          ),
        ],
      ),
    ).animate().fadeIn(delay: Duration(milliseconds: delay)).slideX(begin: -0.1);
  }

  Widget _buildDropdownItem({
    required String label,
    required String value,
    required Map<String, String> options,
    required Function(String?) onChanged,
    int delay = 0,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Container(
        decoration: BoxDecoration(
          color: AppTheme.glassSurface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppTheme.glassBorder),
        ),
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: AppTheme.textSecondary)),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.25),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.glassBorder),
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: options.containsKey(value) ? value : options.keys.first,
                    isExpanded: true,
                    dropdownColor: const Color(0xFF16161B),
                    icon: const Icon(Icons.keyboard_arrow_down_rounded, color: Colors.white54),
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                    items: options.entries.map((entry) {
                      return DropdownMenuItem(
                        value: entry.key,
                        child: Text(entry.value),
                      );
                    }).toList(),
                    onChanged: onChanged,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ).animate().fadeIn(delay: Duration(milliseconds: delay)).slideY(begin: 0.1);
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);
    final currentLocale = ref.watch(localeProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(t.settingsTitle.toUpperCase(), style: Theme.of(context).textTheme.displayMedium?.copyWith(fontSize: 16, letterSpacing: 3)),
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: true,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: AppTheme.primary))
          : _error != null && _error == "not_connected"
              ? Center(child: Text(t.notConnected, style: const TextStyle(color: Colors.redAccent)))
              : ListView(
                  padding: const EdgeInsets.all(16.0).copyWith(bottom: 100),
                  children: [
                    // ── Language Section ──
                    _buildSectionHeader(t.settingsGeneral, Icons.language_rounded, delay: 0),
                    _buildDropdownItem(
                      label: t.settingsLanguage,
                      value: currentLocale,
                      options: supportedLocales,
                      onChanged: (val) {
                        if (val != null) {
                          ref.read(localeProvider.notifier).state = val;
                        }
                      },
                      delay: 100,
                    ),

                    // ── AI Section ──
                    _buildSectionHeader(t.settingsAI, Icons.psychology_rounded, delay: 200),
                    _buildDropdownItem(
                      label: t.settingsAIProvider,
                      value: _llmProvider,
                      options: _llmLabels,
                      onChanged: (val) {
                        if (val != null) {
                          setState(() => _llmProvider = val);
                          if (val == 'ollama') {
                            _saveConfig('auto_route', false, 'llm');
                            _saveConfig('local_provider', 'ollama', 'llm');
                          } else {
                            _saveConfig('cloud_provider', val, 'llm');
                            _saveConfig('auto_route', true, 'llm');
                          }
                        }
                      },
                      delay: 300,
                    ),
                    
                    // ── Voice Section ──
                    _buildSectionHeader(t.settingsVoice, Icons.mic_rounded, delay: 400),
                    _buildDropdownItem(
                      label: t.settingsSTT,
                      value: _sttProvider,
                      options: _sttLabels,
                      onChanged: (val) {
                        if (val != null) {
                          setState(() => _sttProvider = val);
                          _saveConfig('stt_provider', val, 'voice');
                        }
                      },
                      delay: 500,
                    ),
                    _buildDropdownItem(
                      label: t.settingsTTS,
                      value: _ttsProvider,
                      options: _ttsLabels,
                      onChanged: (val) {
                        if (val != null) {
                          setState(() => _ttsProvider = val);
                          _saveConfig('tts_provider', val, 'voice');
                        }
                      },
                      delay: 600,
                    ),
                    
                    const SizedBox(height: 48),
                    ElevatedButton.icon(
                      onPressed: () {
                        ref.read(wsClientProvider).disconnect();
                        ref.read(serverIpProvider.notifier).state = null;
                        Navigator.of(context).pushAndRemoveUntil(
                          MaterialPageRoute(builder: (_) => const ConnectionScreen()),
                          (route) => false,
                        );
                      },
                      icon: const Icon(Icons.logout_rounded, color: Colors.white),
                      label: Text(t.disconnect, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.redAccent.withValues(alpha: 0.15),
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        elevation: 0,
                        side: BorderSide(color: Colors.redAccent.withValues(alpha: 0.5), width: 1),
                      ),
                    ).animate().fadeIn(delay: 800.ms).scale(begin: const Offset(0.9, 0.9)),
                  ],
                ),
    );
  }
}
