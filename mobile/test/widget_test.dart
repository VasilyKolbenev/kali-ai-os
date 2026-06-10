// Basic smoke test for the KALI Mobile app.
//
// Verifies the app boots and shows the connection screen with its Connect
// button. Uses WidgetTester from the flutter_test package.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/main.dart';
import 'package:kali_mobile/presentation/connection_screen.dart';

void main() {
  testWidgets('App boots and shows the connection screen', (WidgetTester tester) async {
    // Build the app and let the entry animations advance a few frames.
    await tester.pumpWidget(const ProviderScope(child: KaliMobileApp()));
    await tester.pump(const Duration(seconds: 1));

    // The first screen is the connection screen with a Connect button.
    expect(find.byType(ConnectionScreen), findsOneWidget);
    expect(find.byType(ElevatedButton), findsOneWidget);
  });
}
