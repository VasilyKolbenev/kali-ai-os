// Widget tests for the share-to-reels agent-card PNG (UGC reel hook).
//
// Covers two things headlessly:
//   1. The card widget renders the agent name, description, QR and branding.
//   2. The capture helper (insert into overlay -> RepaintBoundary.toImage ->
//      PNG) returns non-empty PNG bytes for that card.
//
// The full screen -> native-share-sheet round trip needs an emulator (the OS
// share sheet has no headless harness); that part is verified manually.

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qr_flutter/qr_flutter.dart';

import 'package:kali_mobile/presentation/widgets/share_agent_card.dart';

const _link =
    'kali://import?n=Budget%20Tracker&d=eyJza2lsbCI6ImJ1ZGdldCJ9';

ShareAgentCard _card({String? handle}) => ShareAgentCard(
      agentName: 'Budget Tracker',
      agentDescription: 'Snap a receipt photo and expenses go to Notion!',
      link: _link,
      scanLabel: 'Scan to install the agent',
      tagline: 'Check out the agent I just created by voice!',
      creatorHandle: handle,
    );

void main() {
  testWidgets('card renders agent name, description, QR and branding',
      (tester) async {
    // The card is laid out at a fixed 1080x1350; FittedBox shrinks it to fit
    // the test surface without overflow.
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: FittedBox(child: _card())),
      ),
    );
    await tester.pump();

    expect(find.text('Budget Tracker'), findsOneWidget);
    expect(
      find.text('Snap a receipt photo and expenses go to Notion!'),
      findsOneWidget,
    );
    expect(find.text('Scan to install the agent'), findsOneWidget);
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.text('KALI'), findsOneWidget); // branding present
  });

  testWidgets('card shows the creator handle when provided', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: FittedBox(child: _card(handle: 'vasily'))),
      ),
    );
    await tester.pump();

    expect(find.text('@vasily'), findsOneWidget); // normalised to @handle
  });

  testWidgets('captureCardToPngBytes returns non-empty PNG bytes',
      (tester) async {
    Uint8List? bytes;

    // A tiny harness exposing a BuildContext under an Overlay (MaterialApp
    // provides the root Overlay via its Navigator).
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () async {
                bytes = await captureCardToPngBytes(
                  context,
                  _card(),
                  pixelRatio: 1.5,
                );
              },
              child: const Text('capture'),
            ),
          ),
        ),
      ),
    );

    // toImage needs real async frames -> runAsync escapes the fake-async zone.
    await tester.runAsync(() async {
      await tester.tap(find.text('capture'));
      // Give the overlay child its frames + the toImage round trip time.
      for (var i = 0; i < 6; i++) {
        await tester.pump();
        await Future<void>.delayed(const Duration(milliseconds: 16));
      }
      // Allow the awaited capture future to settle.
      await Future<void>.delayed(const Duration(milliseconds: 100));
    });

    expect(bytes, isNotNull);
    expect(bytes!.isNotEmpty, isTrue);
    // PNG magic number: 0x89 'P' 'N' 'G'.
    expect(bytes!.sublist(0, 4), <int>[0x89, 0x50, 0x4E, 0x47]);
  });
}
