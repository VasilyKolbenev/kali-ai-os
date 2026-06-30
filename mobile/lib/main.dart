import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'presentation/connection_screen.dart';

import 'core/http_client.dart';
import 'core/theme.dart';
import 'core/deep_link_service.dart';

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
  await _initTimezone();

  // Hydrate any previously-paired token before the first request, so a paired
  // phone authenticates on cold start without re-scanning. The container is
  // shared with the running app via UncontrolledProviderScope.
  final container = ProviderContainer();
  await container.read(tokenHolderProvider).loadFromStore();

  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const KaliMobileApp(),
    ),
  );
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
