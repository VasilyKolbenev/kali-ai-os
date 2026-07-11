// Widget tests for the standalone agent chat screen.
//
// Injects a fake chat function (no network / no keychain) and verifies:
//  - a canned reply renders as an assistant bubble;
//  - LlmError.noKey surfaces the "add your AI key" CTA;
//  - other LlmError kinds render an inline honest error.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/l10n.dart';
import 'package:kali_mobile/core/theme.dart';
import 'package:kali_mobile/presentation/standalone_chat_screen.dart';
import 'package:kali_mobile/presentation/widgets/message_bubble.dart';
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

  testWidgets('back-nav mid-request does not crash (mounted guard)',
      (tester) async {
    final gate = Completer<String>();
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) {
      return gate.future; // never resolves until we dispose the screen
    }));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'привет');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump(); // request in flight, awaiting the gate

    // Simulate leaving the screen (dispose) before the reply arrives.
    await tester.pumpWidget(const SizedBox.shrink());
    gate.complete('поздний ответ');
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets('history sent to the model is capped, full thread stays on screen',
      (tester) async {
    var lastHistoryLen = 0;
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) async {
      lastHistoryLen = history.length;
      return 'ok';
    }));
    await tester.pumpAndSettle();

    for (var i = 0; i < 15; i++) {
      await _send(tester, 'сообщение $i');
    }

    // Each send appends user+assistant; 15 rounds = 30 on-screen messages, but
    // the wire history is bounded.
    expect(lastHistoryLen, lessThanOrEqualTo(20));
    expect(find.byType(MessageBubble), findsWidgets); // full thread on screen
  });

  testWidgets('clear-chat empties the thread', (tester) async {
    await tester.pumpWidget(_wrap(({required systemPrompt, required history}) async {
      return 'Привет, я повар.';
    }));
    await tester.pumpAndSettle();
    await _send(tester, 'привет');
    expect(find.text('Привет, я повар.'), findsOneWidget);

    final t = L10n('ru');
    await tester.tap(find.byTooltip(t.chatClear));
    await tester.pumpAndSettle();

    expect(find.text('Привет, я повар.'), findsNothing);
    expect(find.byType(MessageBubble), findsNothing);
  });
}
