// Tests for the standalone deep-link import seam.
//
// `_handleImport` routes a `kali://import` to either the on-device importer
// (standalone / no desktop) or the desktop server. That decision + the
// on-device import action are extracted into pure, injectable functions so they
// can be tested without a Navigator, secure storage, or the network.

import 'dart:async';
import 'dart:convert';

import 'package:archive/archive.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/deep_link_service.dart';
import 'package:kali_mobile/core/l10n.dart';
import 'package:kali_mobile/core/standalone_mode.dart';
import 'package:kali_mobile/presentation/my_agents_screen.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';

import 'scheduling/fake_notification_gateway.dart';

/// In-memory [AgentStore] that records saves.
class _FakeStore implements AgentStore {
  final List<ImportedAgent> saved = [];

  @override
  Future<void> save(ImportedAgent agent) async => saved.add(agent);

  @override
  Future<List<ImportedAgent>> list() async => List.of(saved);

  @override
  Future<ImportedAgent?> get(String name) async {
    for (final a in saved) {
      if (a.name == name) return a;
    }
    return null;
  }

  @override
  Future<void> delete(String name) async =>
      saved.removeWhere((a) => a.name == name);
}

String _payload(String name, String skillMd) {
  final archive = Archive();
  final bytes = utf8.encode(skillMd);
  archive.addFile(ArchiveFile('$name/SKILL.md', bytes.length, bytes));
  final gz = GZipEncoder().encode(TarEncoder().encode(archive));
  return base64Url.encode(gz).replaceAll('=', '');
}

void main() {
  group('shouldImportOnDevice', () {
    test('no desktop paired → on-device', () {
      expect(shouldImportOnDevice(standaloneMode: false, serverIp: null), isTrue);
    });

    test('standalone mode → on-device even if an ip lingers', () {
      expect(shouldImportOnDevice(standaloneMode: true, serverIp: '10.0.2.2'), isTrue);
    });

    test('paired desktop, not standalone → server path', () {
      expect(shouldImportOnDevice(standaloneMode: false, serverIp: '10.0.2.2'), isFalse);
    });
  });

  group('importOnDevice', () {
    test('imports the bundle and saves it to the store', () async {
      final store = _FakeStore();
      const md = '---\nname: chef\ndescription: повар\n---\nТы — повар.';

      final agent = await importOnDevice(_payload('chef', md), store: store);

      expect(agent.name, 'chef');
      expect(store.saved.single.name, 'chef');
      expect(store.saved.single.description, 'повар');
    });

    test('propagates BundleImportError without saving', () async {
      final store = _FakeStore();
      // Not a valid base64url/.tar.gz payload.
      await expectLater(
        () => importOnDevice('not-a-bundle!!!', store: store),
        throwsA(isA<Object>()),
      );
      expect(store.saved, isEmpty);
    });
  });

  group('importStandaloneWithConsent (consent + e2e)', () {
    testWidgets('shows a confirm dialog; no save/permission until Confirm',
        (tester) async {
      final store = _FakeStore();
      final gw = FakeNotificationGateway();
      const md = '---\nname: chef\ndescription: повар\n---\nТы — повар.';
      late WidgetRef capturedRef;
      late BuildContext dialogCtx;

      await tester.pumpWidget(_harness(store, gw, (ref, ctx) {
        capturedRef = ref;
        dialogCtx = ctx;
      }));
      await tester.pumpAndSettle();

      // Kick off the consent-gated import (don't await — the dialog blocks).
      final future = importStandaloneWithConsent(
        data: _payload('chef', md),
        ref: capturedRef,
        t: L10n('ru'),
        messenger: ScaffoldMessenger.of(dialogCtx),
        confirmContext: dialogCtx,
      );
      await tester.pumpAndSettle();

      // Confirm dialog is up, but nothing has been installed yet.
      expect(find.text(L10n('ru').importConfirmTitle), findsOneWidget);
      expect(find.textContaining('chef'), findsWidgets);
      expect(store.saved, isEmpty);
      expect(gw.permissionRequested, isFalse);
      expect(capturedRef.read(standaloneModeProvider), isFalse);

      // Cancel: still nothing installed.
      await tester.tap(find.text(L10n('ru').importConfirmCancel));
      await tester.pumpAndSettle();
      await future;
      expect(store.saved, isEmpty);
      expect(gw.permissionRequested, isFalse);
      expect(capturedRef.read(standaloneModeProvider), isFalse);
    });

    testWidgets('Confirm installs: standalone on, agent on MyAgents, snackbar',
        (tester) async {
      final store = _FakeStore();
      final gw = FakeNotificationGateway();
      const md = '---\nname: chef\ndescription: повар\n---\nТы — повар.';
      late WidgetRef capturedRef;
      late BuildContext dialogCtx;

      await tester.pumpWidget(_harness(store, gw, (ref, ctx) {
        capturedRef = ref;
        dialogCtx = ctx;
      }));
      await tester.pumpAndSettle();

      final messenger = ScaffoldMessenger.of(dialogCtx);
      unawaited(importStandaloneWithConsent(
        data: _payload('chef', md),
        ref: capturedRef,
        t: L10n('ru'),
        messenger: messenger,
        confirmContext: dialogCtx,
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.text(L10n('ru').importConfirmInstall));
      await tester.pumpAndSettle();

      // Persisted + standalone flipped.
      expect(store.saved.single.name, 'chef');
      expect(capturedRef.read(standaloneModeProvider), isTrue);
      // Imported-standalone snackbar shown.
      expect(find.text(L10n('ru').importedStandalone('chef')), findsOneWidget);

      // The imported agent appears on MyAgentsScreen.
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            agentStoreProvider.overrideWithValue(store),
            notificationGatewayProvider.overrideWithValue(gw),
          ],
          child: const MaterialApp(home: MyAgentsScreen()),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('chef'), findsOneWidget);
    });

    testWidgets('malformed bundle: importFailed snackbar, no crash, no save',
        (tester) async {
      final store = _FakeStore();
      final gw = FakeNotificationGateway();
      late WidgetRef capturedRef;
      late BuildContext dialogCtx;

      await tester.pumpWidget(_harness(store, gw, (ref, ctx) {
        capturedRef = ref;
        dialogCtx = ctx;
      }));
      await tester.pumpAndSettle();

      await importStandaloneWithConsent(
        data: 'not-a-bundle!!!',
        ref: capturedRef,
        t: L10n('ru'),
        messenger: ScaffoldMessenger.of(dialogCtx),
        confirmContext: dialogCtx,
      );
      await tester.pumpAndSettle();

      // No confirm dialog, an honest failure, nothing persisted.
      expect(find.text(L10n('ru').importConfirmTitle), findsNothing);
      expect(find.text(L10n('ru').importFailed), findsOneWidget);
      expect(store.saved, isEmpty);
      expect(capturedRef.read(standaloneModeProvider), isFalse);
    });
  });
}

/// Pumps a minimal app exposing a [WidgetRef] + a dialog-capable [BuildContext]
/// (under a Navigator + ScaffoldMessenger) with the on-device providers faked.
Widget _harness(
  AgentStore store,
  NotificationGateway gw,
  void Function(WidgetRef, BuildContext) capture,
) =>
    ProviderScope(
      overrides: [
        agentStoreProvider.overrideWithValue(store),
        notificationGatewayProvider.overrideWithValue(gw),
      ],
      child: MaterialApp(
        home: Consumer(
          builder: (context, ref, _) {
            capture(ref, context);
            return const Scaffold(body: SizedBox.shrink());
          },
        ),
      ),
    );
