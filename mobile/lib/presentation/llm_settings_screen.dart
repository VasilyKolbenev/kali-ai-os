import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n.dart';
import '../core/theme.dart';
import '../standalone/llm_client.dart';
import '../standalone/llm_settings_store.dart';

/// The [LlmSettingsStore] used by the standalone settings screen.
///
/// Overridden in tests with a store backed by an in-memory key/value so no
/// native secure-storage channel is touched.
final llmSettingsStoreProvider = Provider<LlmSettingsStore>(
  (ref) => LlmSettingsStore(),
);

/// BYO-key settings for the standalone cloud-LLM chat: pick a provider and enter
/// an API key. The key is persisted only in OS secure storage on this device.
class LlmSettingsScreen extends ConsumerStatefulWidget {
  const LlmSettingsScreen({super.key});

  @override
  ConsumerState<LlmSettingsScreen> createState() => _LlmSettingsScreenState();
}

class _LlmSettingsScreenState extends ConsumerState<LlmSettingsScreen> {
  final TextEditingController _keyController = TextEditingController();
  LlmProvider _provider = LlmProvider.anthropic;
  bool _loading = true;

  static const Map<LlmProvider, String> _providerLabels = {
    LlmProvider.anthropic: 'Anthropic (Claude)',
    LlmProvider.openai: 'OpenAI (ChatGPT)',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final store = ref.read(llmSettingsStoreProvider);
    final provider = await store.readProvider();
    final key = await store.readApiKey();
    if (!mounted) return;
    setState(() {
      _provider = provider;
      _keyController.text = key ?? '';
      _loading = false;
    });
  }

  @override
  void dispose() {
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final store = ref.read(llmSettingsStoreProvider);
    final t = L10n.of(ref);
    final key = _keyController.text.trim();
    if (key.isEmpty) {
      // Don't silently "save" a blank key — chat would then dead-end with no
      // explanation. Surface an honest error and keep the prior key.
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(t.llmKeyEmpty)),
      );
      return;
    }
    await store.setProvider(_provider);
    await store.setApiKey(key);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(t.llmKeySaved)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(
          t.llmSettingsTitle.toUpperCase(),
          style: Theme.of(context).textTheme.displayMedium?.copyWith(fontSize: 16, letterSpacing: 3),
        ),
        backgroundColor: Colors.transparent,
        centerTitle: true,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppTheme.primary))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  t.llmProviderLabel,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  decoration: BoxDecoration(
                    color: AppTheme.glassSurface,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppTheme.glassBorder),
                  ),
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<LlmProvider>(
                      value: _provider,
                      isExpanded: true,
                      dropdownColor: const Color(0xFF16161B),
                      icon: const Icon(Icons.keyboard_arrow_down_rounded, color: Colors.white54),
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                      items: _providerLabels.entries
                          .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
                          .toList(),
                      onChanged: (val) {
                        if (val != null) setState(() => _provider = val);
                      },
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  t.llmApiKeyLabel,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _keyController,
                  obscureText: true,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: InputDecoration(
                    hintText: 'sk-...',
                    filled: true,
                    fillColor: AppTheme.glassSurface,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                  ),
                  style: const TextStyle(color: Colors.white),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    const Icon(Icons.lock_outline, size: 16, color: AppTheme.textDim),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        t.llmKeyHelper,
                        style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12, height: 1.4),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton(
                    onPressed: _save,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.primary,
                      foregroundColor: Colors.black,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    ),
                    child: Text(t.save, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                ),
              ],
            ),
    );
  }
}
