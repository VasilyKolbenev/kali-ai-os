import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/theme.dart';
import '../core/http_client.dart';
import '../core/l10n.dart';

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  Map<String, dynamic>? _dashboardData;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchDashboardData();
  }

  Future<void> _fetchDashboardData() async {
    final url = apiUrl('/dashboard', ref);
    if (url == null) {
      setState(() => _isLoading = false);
      return;
    }
    
    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get(url);
      if (response.statusCode == 200) {
        setState(() {
          _dashboardData = response.data;
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  String _getGreeting(L10n t) {
    final hour = DateTime.now().hour;
    if (hour < 6) return t.greetNight;
    if (hour < 12) return t.greetMorning;
    if (hour < 18) return t.greetAfternoon;
    return t.greetEvening;
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);
    final insight = _buildInsight(t);

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Stack(
        children: [
          // Ambient background glow — single soft cyan (Refined Futurism)
          Positioned(
            top: -150,
            right: -90,
            child: Container(
              width: 440,
              height: 440,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(
                  colors: [
                    AppTheme.primary.withValues(alpha: 0.16),
                    Colors.transparent,
                  ],
                ),
              ),
            ),
          ).animate().fadeIn(duration: 1200.ms).scale(duration: 1200.ms),
          
          SafeArea(
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                // Header
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _getGreeting(t).toUpperCase(),
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            fontSize: 13,
                            letterSpacing: 2.5,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                        Text(
                          t.userName,
                          style: Theme.of(context).textTheme.displayLarge?.copyWith(
                            fontSize: 32,
                          ),
                        ),
                      ],
                    ).animate().fadeIn(delay: 100.ms).slideX(begin: -0.2),
                    
                    Container(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        boxShadow: [
                          BoxShadow(
                            color: AppTheme.primary.withValues(alpha: 0.3),
                            blurRadius: 15,
                            spreadRadius: -5,
                          ),
                        ],
                      ),
                      child: const CircleAvatar(
                        backgroundColor: AppTheme.cardColor,
                        radius: 26,
                        child: Icon(Icons.person, color: AppTheme.primary),
                      ),
                    ).animate().fadeIn(delay: 200.ms).scale(),
                  ],
                ),
                const SizedBox(height: 40),

                // Proactive insight — honest live summary built from the real
                // dashboard data (weather + tasks). Hidden entirely when not
                // connected, so the card never shows a fabricated briefing.
                if (insight != null) ...[
                  Container(
                    decoration: BoxDecoration(
                      color: AppTheme.glassSurface,
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(color: AppTheme.primary.withValues(alpha: 0.22)),
                      boxShadow: [
                        BoxShadow(
                          color: AppTheme.primary.withValues(alpha: 0.12),
                          blurRadius: 34,
                          spreadRadius: -8,
                          offset: const Offset(0, 8),
                        )
                      ],
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(28),
                      child: BackdropFilter(
                        filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  const Icon(Icons.auto_awesome, color: AppTheme.primary, size: 22)
                                    .animate(onPlay: (controller) => controller.repeat(reverse: true))
                                    .scaleXY(end: 1.1, duration: 1.seconds),
                                  const SizedBox(width: 10),
                                  Text(
                                    t.insightTitle,
                                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                                      color: AppTheme.primary,
                                      fontWeight: FontWeight.bold,
                                      letterSpacing: 1.2,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 16),
                              Text(
                                insight,
                                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                                  fontSize: 16,
                                  height: 1.5,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ).animate().fadeIn(delay: 300.ms).slideY(begin: 0.2),
                  const SizedBox(height: 40),
                ],

                // Widgets Grid
                Text(
                  t.lifeGlance.toUpperCase(),
                  style: Theme.of(context).textTheme.displayMedium?.copyWith(
                    fontSize: 15,
                    letterSpacing: 2,
                    color: AppTheme.textDim,
                  ),
                ).animate().fadeIn(delay: 500.ms),
                const SizedBox(height: 20),
                Row(
                  children: [
                    Expanded(
                      child: _buildGlassWidget(
                        context: context,
                        icon: Icons.wb_sunny_rounded,
                        color: Colors.orangeAccent,
                        title: t.weather,
                        value: _dashboardData?['weather']?['temp'] ?? '\u2014',
                        subtitle: _localizeCondition(
                            _dashboardData?['weather']?['condition'] as String?, t.locale),
                        delay: 600,
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: _buildGlassWidget(
                        context: context,
                        icon: Icons.account_balance_wallet_rounded,
                        color: Colors.greenAccent,
                        title: t.budget,
                        value: _dashboardData?['budget']?['amount'] ?? '\u2014',
                        subtitle: _dashboardData?['budget']?['status'] ?? '',
                        delay: 700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                _buildGlassWidget(
                  context: context,
                  icon: Icons.check_circle_rounded,
                  color: AppTheme.primary,
                  title: t.tasks,
                  value: t.active(_dashboardData?['tasks']?['active'] ?? 0),
                  subtitle: _dashboardData?['tasks']?['subtitle'] ?? '',
                  isFullWidth: true,
                  delay: 800,
                ),
                const SizedBox(height: 40), // Padding for bottom nav
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// Honest one-line insight built from the live dashboard data. Returns null
  /// when there is no data (not connected) so the card is hidden rather than
  /// showing a fabricated briefing.
  String? _buildInsight(L10n t) {
    final d = _dashboardData;
    if (d == null) return null;
    final parts = <String>[];
    final temp = d['weather']?['temp'] as String?;
    if (temp != null && temp.isNotEmpty && temp != '—') {
      final cond = _localizeCondition(d['weather']?['condition'] as String?, t.locale);
      parts.add(t.insightWeather(cond.isEmpty ? temp : '$temp, $cond'));
    }
    final active = ((d['tasks']?['active'] ?? 0) as num).toInt();
    parts.add(active > 0 ? t.insightTasksActive(active) : t.insightNoTasks);
    final amount = d['budget']?['amount'] as String?;
    parts.add(amount == null || amount.isEmpty || amount == '—'
        ? t.insightNoSpending
        : t.insightSpending(amount));
    return parts.isEmpty ? null : parts.join('  ·  ');
  }

  /// Localize an English Open-Meteo weather condition to the UI locale. The
  /// keys mirror `agents/weather` WMO_CODES one-for-one, so every condition the
  /// backend can emit has a Russian form. Only Russian (the primary audience)
  /// is mapped; other locales keep the source English. Unknown codes (the
  /// agent's "Unknown" fallback) pass through unchanged.
  String _localizeCondition(String? condition, String locale) {
    if (condition == null || condition.isEmpty) return '';
    if (locale != 'ru') return condition;
    const ru = {
      'Clear sky': 'ясно',
      'Mainly clear': 'ясно',
      'Partly cloudy': 'облачно',
      'Overcast': 'пасмурно',
      'Foggy': 'туман',
      'Rime fog': 'туман',
      'Light drizzle': 'морось',
      'Moderate drizzle': 'морось',
      'Dense drizzle': 'сильная морось',
      'Slight rain': 'небольшой дождь',
      'Moderate rain': 'дождь',
      'Heavy rain': 'сильный дождь',
      'Slight snow': 'небольшой снег',
      'Moderate snow': 'снег',
      'Heavy snow': 'сильный снег',
      'Slight rain showers': 'ливень',
      'Moderate rain showers': 'ливень',
      'Violent rain showers': 'сильный ливень',
      'Thunderstorm': 'гроза',
      'Thunderstorm with hail': 'гроза с градом',
    };
    return ru[condition] ?? condition;
  }

  Widget _buildGlassWidget({
    required BuildContext context,
    required IconData icon,
    required Color color,
    required String title,
    required String value,
    required String subtitle,
    bool isFullWidth = false,
    required int delay,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppTheme.glassSurface,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: AppTheme.glassBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppTheme.primary.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: AppTheme.primary, size: 20),
              ),
              const SizedBox(width: 12),
              Text(
                title.toUpperCase(),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: 11,
                  letterSpacing: 1.5,
                  color: AppTheme.textDim,
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Text(
            value,
            style: Theme.of(context).textTheme.displayLarge?.copyWith(
              fontSize: 26,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              fontSize: 13,
              color: AppTheme.textDim,
            ),
          ),
        ],
      ),
    ).animate().fadeIn(delay: delay.ms).slideY(begin: 0.1);
  }
}
