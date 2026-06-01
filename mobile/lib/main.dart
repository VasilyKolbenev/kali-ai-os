import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'presentation/connection_screen.dart';

import 'core/theme.dart';

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
      theme: AppTheme.darkTheme,
      home: const ConnectionScreen(),
    );
  }
}
