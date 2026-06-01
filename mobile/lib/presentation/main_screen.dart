import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'dart:ui';
import '../core/theme.dart';
import '../core/l10n.dart';
import 'dashboard_screen.dart';
import 'voice_screen.dart';
import 'chat_screen.dart';
import 'agent_store_screen.dart';
import 'settings_screen.dart';

class MainScreen extends ConsumerStatefulWidget {
  const MainScreen({super.key});

  @override
  ConsumerState<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends ConsumerState<MainScreen> {
  int _currentIndex = 0;

  final List<Widget> _screens = [
    const DashboardScreen(),
    const VoiceScreen(),
    const ChatScreen(),
    const AgentStoreScreen(),
    const SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: AppTheme.background,
      body: Stack(
        children: [
          _screens[_currentIndex],
          
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
                    color: AppTheme.cardColor,
                    borderRadius: BorderRadius.circular(30),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.3),
                        blurRadius: 20,
                        offset: const Offset(0, 10),
                      )
                    ],
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      _buildNavItem(0, Icons.dashboard_outlined, Icons.dashboard_rounded, t.navHome),
                      _buildNavItem(1, Icons.mic_none_rounded, Icons.mic_rounded, t.navVoice),
                      _buildNavItem(2, Icons.chat_bubble_outline_rounded, Icons.chat_bubble_rounded, t.navChat),
                      _buildNavItem(3, Icons.smart_toy_outlined, Icons.smart_toy_rounded, t.navAgents),
                      _buildNavItem(4, Icons.settings_outlined, Icons.settings_rounded, t.navSettings),
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
