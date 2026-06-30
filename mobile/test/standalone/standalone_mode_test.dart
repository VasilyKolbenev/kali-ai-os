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
    await tester.pumpAndSettle();

    expect(container.read(standaloneModeProvider), isTrue);
    expect(find.byType(MainScreen), findsOneWidget);
  });
}
