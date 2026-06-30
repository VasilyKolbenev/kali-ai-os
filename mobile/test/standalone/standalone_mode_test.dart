// Tests for the standalone-mode flag + the connection-screen entry button.
//
// The provider test is pure Riverpod. The widget test pumps the connection
// screen and verifies the «Использовать без компьютера» button flips the flag
// and routes to MainScreen — without touching any native channel.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/l10n.dart';
import 'package:kali_mobile/core/standalone_mode.dart';
import 'package:kali_mobile/core/theme.dart';
import 'package:kali_mobile/presentation/connection_screen.dart';
import 'package:kali_mobile/presentation/main_screen.dart';
import 'package:kali_mobile/presentation/my_agents_screen.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';

/// Empty in-memory store so the standalone MainScreen (which renders
/// MyAgentsScreen) doesn't touch the native path_provider channel.
class _EmptyStore implements AgentStore {
  @override
  Future<void> save(ImportedAgent agent) async {}
  @override
  Future<List<ImportedAgent>> list() async => const [];
  @override
  Future<ImportedAgent?> get(String name) async => null;
  @override
  Future<void> delete(String name) async {}
}

void main() {
  test('standaloneModeProvider defaults to false and toggles', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(standaloneModeProvider), isFalse);
    container.read(standaloneModeProvider.notifier).state = true;
    expect(container.read(standaloneModeProvider), isTrue);
  });

  testWidgets('«Использовать без компьютера» sets the flag and navigates',
      (tester) async {
    late ProviderContainer container;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentStoreProvider.overrideWithValue(_EmptyStore())],
        child: Consumer(
          builder: (context, ref, _) {
            container = ProviderScope.containerOf(context);
            return MaterialApp(
              theme: AppTheme.darkTheme,
              home: const ConnectionScreen(),
            );
          },
        ),
      ),
    );
    await tester.pump(const Duration(seconds: 1));

    final t = L10n('ru');
    final button = find.text(t.useWithoutComputer);
    expect(button, findsOneWidget);

    await tester.tap(button);
    // Bounded pumps (not pumpAndSettle) — MainScreen has perpetual entry
    // animations that never settle.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));

    expect(container.read(standaloneModeProvider), isTrue);
    expect(find.byType(MainScreen), findsOneWidget);
  });
}
