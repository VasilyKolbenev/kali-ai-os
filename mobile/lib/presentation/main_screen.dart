import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'dart:ui';
import '../core/theme.dart';
import '../core/l10n.dart';
import '../core/standalone_mode.dart';
import 'dashboard_screen.dart';
import 'voice_screen.dart';
import 'chat_screen.dart';
import 'agent_store_screen.dart';
import 'settings_screen.dart';
import 'my_agents_screen.dart';
import 'llm_settings_screen.dart';
// reminderSchedulerProvider + guardedSyncAll are declared in my_agents_screen.dart.

class MainScreen extends ConsumerStatefulWidget {
  const MainScreen({super.key});

  @override
  ConsumerState<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends ConsumerState<MainScreen>
    with WidgetsBindingObserver {
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Top up scheduled reminders whenever the app returns to the foreground —
    // the app-open half of the pre-schedule + top-up strategy. Guarded so a
    // bad agent file logs instead of throwing an unhandled async error that
    // would poison the resume handler.
    if (state == AppLifecycleState.resumed) {
      guardedSyncAll(ref.read(reminderSchedulerProvider), DateTime.now());
    }
  }

  static const List<Widget> _tetheredScreens = [
    DashboardScreen(),
    VoiceScreen(),
    ChatScreen(),
    AgentStoreScreen(),
    SettingsScreen(),
  ];

  static const List<Widget> _standaloneScreens = [
    MyAgentsScreen(),
    LlmSettingsScreen(),
  ];

  /// Nav items (inactive icon, active icon, label) for the current mode.
  List<({IconData icon, IconData active, String label})> _navItems(L10n t, bool standalone) {
    if (standalone) {
      return [
        (icon: Icons.smart_toy_outlined, active: Icons.smart_toy_rounded, label: t.myAgentsTitle),
        (icon: Icons.settings_outlined, active: Icons.settings_rounded, label: t.navSettings),
      ];
    }
    return [
      (icon: Icons.dashboard_outlined, active: Icons.dashboard_rounded, label: t.navHome),
      (icon: Icons.mic_none_rounded, active: Icons.mic_rounded, label: t.navVoice),
      (icon: Icons.chat_bubble_outline_rounded, active: Icons.chat_bubble_rounded, label: t.navChat),
      (icon: Icons.smart_toy_outlined, active: Icons.smart_toy_rounded, label: t.navAgents),
      (icon: Icons.settings_outlined, active: Icons.settings_rounded, label: t.navSettings),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);
    final standalone = ref.watch(standaloneModeProvider);
    final screens = standalone ? _standaloneScreens : _tetheredScreens;
    final navItems = _navItems(t, standalone);
    final index = _currentIndex.clamp(0, screens.length - 1);

    return Scaffold(
      backgroundColor: AppTheme.background,
      body: Stack(
        children: [
          screens[index],

          // Custom Glassmorphic Bottom Navigation
          Positioned(
            left: 20,
            right: 20,
            bottom: 30,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(30),
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
                child: Container(
                  height: 70,
                  decoration: BoxDecoration(
                    color: AppTheme.glassSurface,
                    borderRadius: BorderRadius.circular(30),
                    border: Border.all(color: AppTheme.glassBorder),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.25),
                        blurRadius: 24,
                        offset: const Offset(0, 8),
                      )
                    ],
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      for (var i = 0; i < navItems.length; i++)
                        _buildNavItem(i, navItems[i].icon, navItems[i].active, navItems[i].label),
                    ],
                  ),
                ),
              ),
            ),
          ).animate().slideY(begin: 1, delay: 500.ms).fadeIn(),
        ],
      ),
    );
  }

  Widget _buildNavItem(int index, IconData icon, IconData activeIcon, String label) {
    final isSelected = _currentIndex == index;
    final color = isSelected ? AppTheme.primary : AppTheme.textSecondary;
    
    return GestureDetector(
      onTap: () {
        setState(() {
          _currentIndex = index;
        });
      },
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOutQuint,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              isSelected ? activeIcon : icon,
              color: color,
              size: isSelected ? 26 : 24,
            ).animate(target: isSelected ? 1 : 0).scale(end: const Offset(1.1, 1.1)),
            const SizedBox(height: 4),
            Text(
              label,
              style: TextStyle(
                color: color,
                fontSize: 10,
                fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
