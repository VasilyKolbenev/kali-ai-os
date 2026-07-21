// OPUS-301: the Dart Anthropic defaults must stay in sync with the shared JSON
// SoT (config/model_registry.json) and migrate retired ids to the active default.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/llm_client.dart';

void main() {
  group('activeAnthropicModel migration', () {
    test('migrates a retired id to the default', () {
      expect(
        activeAnthropicModel('claude-sonnet-4-20250514'),
        kAnthropicDefaultModel,
      );
    });

    test('leaves an active id unchanged', () {
      expect(activeAnthropicModel('claude-opus-4-8'), 'claude-opus-4-8');
    });

    test('falls back to default for null/empty', () {
      expect(activeAnthropicModel(null), kAnthropicDefaultModel);
      expect(activeAnthropicModel(''), kAnthropicDefaultModel);
    });
  });

  test('dart defaults match the JSON SoT', () {
    // Repo-root file relative to the mobile/ package cwd. Guard skip-if-missing
    // so out-of-tree packaging does not hard-fail (F10).
    final file = File('../config/model_registry.json');
    if (!file.existsSync()) {
      return; // SoT not reachable in this layout — nothing to assert.
    }
    final reg = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
    final anthropic =
        (reg['providers'] as Map<String, dynamic>)['anthropic'] as Map<String, dynamic>;

    expect(kAnthropicDefaultModel, anthropic['default']);
    expect(
      kAnthropicRetiredModels,
      (anthropic['retired'] as List).cast<String>(),
    );
    for (final r in kAnthropicRetiredModels) {
      expect((anthropic['models'] as List).contains(r), isFalse);
    }
  });
}
