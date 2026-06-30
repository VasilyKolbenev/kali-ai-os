// Widget tests for the standalone agent chat screen.
//
// Injects a fake chat function (no network / no keychain) and verifies:
//  - a canned reply renders as an assistant bubble;
//  - LlmError.noKey surfaces the "add your AI key" CTA;
//  - other LlmError kinds render an inline honest error.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/l10n.dart';
import 'package:kali_mobile/core/theme.dart';
import 'package:kali_mobile/presentation/standalone_chat_screen.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/llm_client.dart';

final _agent = ImportedAgent(
  name: 'chef',
  description: 'повар',
  skillMd: '---\nname: chef\n---\nТы — повар.',
  installedAt: DateTime.utc(2026, 6, 29),
);

Widget _wrap(ChatFn chat) => ProviderScope(
      overrides: [chatFnProvider.overrideWithValue(chat)],
      child: MaterialApp(
        theme: AppTheme.darkTheme,
        home: StandaloneChatScreen(agent: _agent),
      ),
    );

Future<void> _send(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.testTextInput.receiveAction(TextInputAction.done);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('canned reply renders as an assistant bubble', (tester) async {
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) async {
      return 'Привет, я повар.';
    }));
    await tester.pumpAndSettle();

    await _send(tester, 'привет');

    expect(find.text('Привет, я повар.'), findsOneWidget);
  });

  testWidgets('passes the agent SKILL.md as the system prompt', (tester) async {
    String? capturedSystem;
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) async {
      capturedSystem = systemPrompt;
      return 'ok';
    }));
    await tester.pumpAndSettle();

    await _send(tester, 'привет');

    expect(capturedSystem, _agent.skillMd);
  });

  testWidgets('noKey error shows the add-key CTA', (tester) async {
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) async {
      throw LlmError(LlmErrorKind.noKey);
    }));
    await tester.pumpAndSettle();

    await _send(tester, 'привет');

    final t = L10n('ru');
    expect(find.text(t.llmAddKeyCta), findsOneWidget);
  });

  testWidgets('network error renders an inline honest message', (tester) async {
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) async {
      throw LlmError(LlmErrorKind.network);
    }));
    await tester.pumpAndSettle();

    await _send(tester, 'привет');

    final t = L10n('ru');
    expect(find.text(t.llmErrorNetwork), findsOneWidget);
  });
}
