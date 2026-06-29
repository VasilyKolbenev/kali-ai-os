import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'presentation/connection_screen.dart';

import 'core/http_client.dart';
import 'core/theme.dart';
import 'core/deep_link_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

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
