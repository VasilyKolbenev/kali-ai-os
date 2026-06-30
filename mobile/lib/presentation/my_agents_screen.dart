import 'dart:developer';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../core/l10n.dart';
import '../core/theme.dart';
import '../standalone/agent_store.dart';
import '../standalone/imported_agent.dart';
import '../standalone/scheduling/notification_gateway.dart';
import '../standalone/scheduling/reminder_config.dart';
import '../standalone/scheduling/reminder_schedule.dart';
import '../standalone/scheduling/reminder_scheduler.dart';
import 'standalone_chat_screen.dart';

/// The on-device [AgentStore]. Overridden in tests with a fake so no native
/// `path_provider` channel is touched.
final agentStoreProvider = Provider<AgentStore>((ref) => FileAgentStore());

/// The native notification gateway. Overridden in tests with a fake so no
/// native plugin channel is touched.
final notificationGatewayProvider = Provider<NotificationGateway>(
  (ref) => LocalNotificationGateway(FlutterLocalNotificationsPlugin()),
);

/// Schedules reminder agents from the on-device store via the gateway.
final reminderSchedulerProvider = Provider<ReminderScheduler>(
  (ref) => ReminderScheduler(
    store: ref.read(agentStoreProvider),
    gateway: ref.read(notificationGatewayProvider),
  ),
);

/// Awaits [scheduler.syncAll], swallowing+logging any failure so a single bad
/// agent file can't become an unhandled async error (which would poison the
/// app-resume handler / tile bootstrap and silently desync reminders).
Future<void> guardedSyncAll(ReminderScheduler scheduler, DateTime now) async {
  try {
    await scheduler.syncAll(now);
  } on Object catch (e, st) {
    log('reminder syncAll failed', name: 'ReminderScheduler', error: e, stackTrace: st);
  }
}

/// Lists the agents imported on-device (standalone mode). Tapping a
/// conversational agent opens a chat with it via the cloud LLM
/// ([StandaloneChatScreen]); a reminder agent gets an inline on/off toggle,
/// the next fire time and a snooze action.
class MyAgentsScreen extends ConsumerStatefulWidget {
  const MyAgentsScreen({super.key});

  @override
  ConsumerState<MyAgentsScreen> createState() => _MyAgentsScreenState();
}

class _MyAgentsScreenState extends ConsumerState<MyAgentsScreen> {
  late Future<List<ImportedAgent>> _agents;

  /// Whether OS notification permission is granted. Resolved ONCE at the screen
  /// level (not per tile) and passed down to every [_ReminderTile].
  bool? _permissionGranted;

  @override
  void initState() {
    super.initState();
    _agents = ref.read(agentStoreProvider).list();
    _bootstrapReminders();
  }

  /// Requests permission once and runs a SINGLE store-wide [syncAll] for the
  /// whole screen. Previously each reminder tile did this on build, causing
  /// O(N²) cancel/reschedule churn (and amplifying the syncAll race). Awaited +
  /// guarded so a failure logs instead of becoming an unhandled async error.
  Future<void> _bootstrapReminders() async {
    await guardedSyncAll(ref.read(reminderSchedulerProvider), DateTime.now());
    // Only prompt for notification permission when the user actually has a
    // reminder agent — a chat-only user shouldn't get an OS permission dialog
    // for a capability they don't use yet.
    final List<ImportedAgent> agents;
    try {
      agents = await _agents;
    } catch (_) {
      return; // list() failure is surfaced by the FutureBuilder, not here
    }
    if (!agents.any((a) => a.template == 'reminder')) return;
    final granted =
        await ref.read(notificationGatewayProvider).requestPermission();
    if (!mounted) return;
    setState(() => _permissionGranted = granted);
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(
          t.myAgentsTitle.toUpperCase(),
          style: Theme.of(context).textTheme.displayMedium?.copyWith(fontSize: 16, letterSpacing: 3),
        ),
        backgroundColor: Colors.transparent,
        centerTitle: true,
      ),
      body: FutureBuilder<List<ImportedAgent>>(
        future: _agents,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator(color: AppTheme.primary));
          }
          if (snapshot.hasError) {
            return _errorState(context, t);
          }
          final agents = snapshot.data ?? const <ImportedAgent>[];
          if (agents.isEmpty) {
            return _emptyState(context, t);
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: agents.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (context, index) => _agentTile(context, agents[index]),
          );
        },
      ),
    );
  }

  /// Surfaces a `list()` failure honestly (instead of the misleading
  /// empty-state) with a retry that re-reads the store.
  Widget _errorState(BuildContext context, L10n t) => Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 40),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline_rounded,
                  size: 64, color: AppTheme.accent.withValues(alpha: 0.6)),
              const SizedBox(height: 16),
              Text(
                t.myAgentsError,
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .bodyLarge
                    ?.copyWith(color: AppTheme.textSecondary),
              ),
              const SizedBox(height: 16),
              TextButton.icon(
                onPressed: () =>
                    setState(() => _agents = ref.read(agentStoreProvider).list()),
                icon: const Icon(Icons.refresh_rounded, color: AppTheme.primary),
                label: Text(t.retry, style: const TextStyle(color: AppTheme.primary)),
              ),
            ],
          ),
        ),
      );

  Widget _emptyState(BuildContext context, L10n t) => Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 40),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.smart_toy_outlined, size: 64, color: AppTheme.textSecondary.withValues(alpha: 0.2)),
              const SizedBox(height: 16),
              Text(
                t.myAgentsEmpty,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: AppTheme.textSecondary),
              ),
            ],
          ),
        ),
      );

  Widget _agentTile(BuildContext context, ImportedAgent agent) {
    if (agent.template == 'reminder') {
      return _ReminderTile(agent: agent, permissionGranted: _permissionGranted);
    }
    return _glassTile(
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: const Icon(Icons.smart_toy_rounded, color: AppTheme.primary),
        title: Text(agent.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
        subtitle: agent.description.isEmpty
            ? null
            : Text(agent.description, style: const TextStyle(color: AppTheme.textSecondary)),
        trailing: const Icon(Icons.chevron_right_rounded, color: AppTheme.textDim),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => StandaloneChatScreen(agent: agent)),
        ),
      ),
    );
  }
}

/// Shared frosted-glass container used by every agent tile.
Widget _glassTile({required Widget child}) => Container(
      decoration: BoxDecoration(
        color: AppTheme.glassSurface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.glassBorder),
      ),
      child: Material(type: MaterialType.transparency, child: child),
    );

/// A reminder agent row: on/off [Switch], the next fire time, an "Отложить на
/// час" snooze action, and an honest note when notification permission is
/// denied. Toggle/snooze re-sync the OS schedule; the screen owns the one-shot
/// permission request + initial store-wide sync ([permissionGranted] is passed
/// down rather than re-resolved per tile).
class _ReminderTile extends ConsumerStatefulWidget {
  const _ReminderTile({required this.agent, required this.permissionGranted});

  final ImportedAgent agent;

  /// Screen-resolved permission state; null until the one-shot request settles.
  final bool? permissionGranted;

  @override
  ConsumerState<_ReminderTile> createState() => _ReminderTileState();
}

class _ReminderTileState extends ConsumerState<_ReminderTile> {
  late bool _enabled = widget.agent.enabled;
  DateTime? _snoozeUntil;

  @override
  void initState() {
    super.initState();
    _snoozeUntil = widget.agent.snoozeUntil;
  }

  Future<void> _onToggle(bool value) async {
    setState(() => _enabled = value);
    await ref.read(reminderSchedulerProvider).setEnabled(widget.agent.name, value);
  }

  Future<void> _onSnooze() async {
    await ref
        .read(reminderSchedulerProvider)
        .snooze(widget.agent.name, const Duration(hours: 1));
    final clock = DateTime.now();
    if (!mounted) return;
    setState(() => _snoozeUntil = clock.add(const Duration(hours: 1)));
    final t = L10n.of(ref);
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(t.reminderSnoozed)));
  }

  /// "HH:mm" of the next fire within the next day, or null if none upcoming.
  String? _nextFireLabel() {
    final cfg = parseReminderConfig(
      widget.agent.config ?? const {},
      fallbackMessage: widget.agent.description,
    );
    final now = DateTime.now();
    final from = (_snoozeUntil != null && _snoozeUntil!.isAfter(now))
        ? _snoozeUntil!
        : now;
    final times = nextFireTimes(
      config: cfg,
      from: from,
      horizonEnd: now.add(const Duration(days: 1)),
      maxCount: 1,
    );
    if (times.isEmpty) return null;
    final d = times.first;
    return '${d.hour.toString().padLeft(2, '0')}:'
        '${d.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);
    final next = _enabled ? _nextFireLabel() : null;
    final denied = widget.permissionGranted == false;

    final subtitle = <Widget>[
      Text(
        _enabled
            ? (next != null ? t.reminderNextFire(next) : t.reminderNextFireNone)
            : widget.agent.description,
        style: const TextStyle(color: AppTheme.textSecondary),
      ),
      if (denied) ...[
        const SizedBox(height: 4),
        Row(
          children: [
            const Icon(Icons.notifications_off_outlined,
                size: 14, color: AppTheme.accent),
            const SizedBox(width: 4),
            Expanded(
              child: Text(
                t.reminderPermissionNeeded,
                style: const TextStyle(color: AppTheme.accent, fontSize: 12),
              ),
            ),
          ],
        ),
      ],
    ];

    return _glassTile(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.alarm_rounded, color: AppTheme.primary),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.agent.name,
                        style: const TextStyle(
                            color: Colors.white, fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 2),
                      ...subtitle,
                    ],
                  ),
                ),
                Switch(
                  value: _enabled,
                  activeThumbColor: AppTheme.primary,
                  onChanged: _onToggle,
                ),
              ],
            ),
            if (_enabled)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: _onSnooze,
                  icon: const Icon(Icons.snooze_rounded,
                      size: 18, color: AppTheme.textSecondary),
                  label: Text(
                    t.reminderSnoozeHour,
                    style: const TextStyle(color: AppTheme.textSecondary),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
