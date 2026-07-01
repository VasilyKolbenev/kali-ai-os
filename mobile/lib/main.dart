import 'dart:developer' as developer;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'presentation/connection_screen.dart';

import 'core/http_client.dart';
import 'core/theme.dart';
import 'core/deep_link_service.dart';
import 'standalone/scheduling/notification_gateway.dart';

/// Initialise the timezone database and pin it to the device's local zone, so
/// the standalone reminder scheduler's `tz.TZDateTime.from(when, tz.local)`
/// interprets fire times in wall-clock local time. Without this `tz.local`
/// defaults to UTC and reminders would fire hours off. Honest degradation: if
/// the platform zone can't be read we leave the UTC default rather than crash.
Future<void> _initTimezone() async {
  tzdata.initializeTimeZones();
  try {
    final info = await FlutterTimezone.getLocalTimezone();
    tz.setLocalLocation(tz.getLocation(info.identifier));
  } on Exception {
    // Keep the UTC fallback; reminders still fire, just interpreted as UTC.
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final container = ProviderContainer();
  await bootstrap(
    initTimezone: _initTimezone,
    initNotifications: initializeNotifications,
    loadToken: container.read(tokenHolderProvider).loadFromStore,
    runApp: (app) => runApp(
      UncontrolledProviderScope(container: container, child: app),
    ),
  );
}

/// Runs each pre-`runApp` side-effect under its own guard, then mounts the app.
///
/// Cold-start crash-safety: a throw in notification init, timezone setup or
/// token hydration must never white-screen the app. Each side-effect degrades
/// honestly (notif fail → reminders unavailable; token fail → unpaired) and
/// [runApp] is reached unconditionally. The side-effects + [runApp] are injected
/// so this is testable off-device with throwing stubs.
Future<void> bootstrap({
  required Future<void> Function() initTimezone,
  required Future<void> Function() initNotifications,
  required Future<void> Function() loadToken,
  required void Function(Widget app) runApp,
}) async {
  await _guard('timezone init', initTimezone);
  // Reminders need the notification plugin + channel; if init fails they're
  // unavailable, but the app still boots.
  await _guard('notification init', initNotifications);
  // Hydrate any previously-paired token so a paired phone authenticates on cold
  // start without re-scanning; on failure the phone simply starts unpaired.
  await _guard('token hydration', loadToken);

  runApp(const KaliMobileApp());
}

/// Awaits [action], logging and swallowing any error so cold start proceeds.
Future<void> _guard(String label, Future<void> Function() action) async {
  try {
    await action();
  } on Object catch (e, st) {
    developer.log('startup: $label failed; degrading',
        name: 'kali.bootstrap', error: e, stackTrace: st);
  }
}

class KaliMobileApp extends StatelessWidget {
  const KaliMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KALI Mobile',
      navigatorKey: navigatorKey,
      scaffoldMessengerKey: scaffoldMessengerKey,
      theme: AppTheme.darkTheme,
      home: const DeepLinkHandler(child: ConnectionScreen()),
    );
  }
}
