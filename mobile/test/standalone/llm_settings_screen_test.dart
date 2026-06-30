// Widget test for the LLM settings screen.
//
// Verifies that choosing a provider + entering an API key persists via an
// injected [LlmSettingsStore] backed by an in-memory key/value store — no real
// secure storage channel is touched.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/l10n.dart';
import 'package:kali_mobile/core/theme.dart';
import 'package:kali_mobile/presentation/llm_settings_screen.dart';
import 'package:kali_mobile/standalone/llm_client.dart';
import 'package:kali_mobile/standalone/llm_settings_store.dart';

/// In-memory [LlmKeyValueStore] for tests.
class _MemoryKv implements LlmKeyValueStore {
  final Map<String, String> data = {};

  @override
  Future<void> write(String key, String value) async => data[key] = value;

  @override
  Future<String?> read(String key) async => data[key];

  @override
  Future<void> delete(String key) async => data.remove(key);
}

void main() {
  testWidgets('saving a key + provider persists via the store', (tester) async {
    final kv = _MemoryKv();
    final store = LlmSettingsStore(storage: kv);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          llmSettingsStoreProvider.overrideWithValue(store),
        ],
        child: MaterialApp(
          theme: AppTheme.darkTheme,
          home: const LlmSettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Enter an API key.
    await tester.enterText(find.byType(TextField), 'sk-test-123');
    await tester.pump();

    // Save.
    final t = L10n('ru');
    await tester.tap(find.text(t.save));
    await tester.pumpAndSettle();

    expect(kv.data[kLlmApiKeyKey], 'sk-test-123');
    // Default provider persisted too.
    expect(kv.data[kLlmProviderKey], LlmProvider.anthropic.name);
  });
}
