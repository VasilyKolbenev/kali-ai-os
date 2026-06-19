import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'presentation/connection_screen.dart';

import 'core/theme.dart';
import 'core/deep_link_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    const ProviderScope(
      child: KaliMobileApp(),
    ),
  );
}

class KaliMobileApp extends StatelessWidget {
  const KaliMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KALI Mobile',
      scaffoldMessengerKey: scaffoldMessengerKey,
      theme: AppTheme.darkTheme,
      home: const DeepLinkHandler(child: ConnectionScreen()),
    );
  }
}
