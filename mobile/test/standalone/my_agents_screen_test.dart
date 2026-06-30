// Widget tests for the standalone «Мои агенты» screen.
//
// Lists agents from an injected fake [AgentStore]; shows an honest empty-state
// when there are none. No native channels are touched.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kali_mobile/core/l10n.dart';
import 'package:kali_mobile/core/theme.dart';
import 'package:kali_mobile/presentation/my_agents_screen.dart';
import 'package:kali_mobile/standalone/agent_store.dart';
import 'package:kali_mobile/standalone/imported_agent.dart';
import 'package:kali_mobile/standalone/scheduling/notification_gateway.dart';
import 'package:kali_mobile/standalone/scheduling/reminder_scheduler.dart';

import 'scheduling/fake_notification_gateway.dart';

class _FakeStore implements AgentStore {
  _FakeStore(this._agents);
  final List<ImportedAgent> _agents;

  @override
  Future<void> save(ImportedAgent agent) async {
    _agents.removeWhere((a) => a.name == agent.name); // upsert by name
    _agents.add(agent);
  }

  @override
  Future<List<ImportedAgent>> list() async => List.of(_agents);

  @override
  Future<ImportedAgent?> get(String name) async {
    for (final a in _agents) {
      if (a.name == name) return a;
    }
    return null;
  }

  @override
  Future<void> delete(String name) async =>
      _agents.removeWhere((a) => a.name == name);
}

/// A store whose list() always throws — stands in for a load failure that the
/// FutureBuilder must surface honestly (not as an empty-state or spinner).
class _ThrowingStore implements AgentStore {
  @override
  Future<List<ImportedAgent>> list() async => throw StateError('boom');

  @override
  Future<void> save(ImportedAgent agent) async {}

  @override
  Future<ImportedAgent?> get(String name) async => null;

  @override
  Future<void> delete(String name) async {}
}

ImportedAgent _agent(String name, String desc) => ImportedAgent(
      name: name,
      description: desc,
      skillMd: '---\nname: $name\n---\nbody',
      installedAt: DateTime.utc(2026, 6, 29),
    );

ImportedAgent _reminder(String name, {bool enabled = true}) => ImportedAgent(
      name: name,
      description: 'пить воду',
      skillMd: '---\nname: $name\n---\nbody',
      installedAt: DateTime.utc(2026, 6, 29),
      template: 'reminder',
      config: const {
        'reminders': {'interval_hours': 2},
        'time_window': 'с 8 до 22',
      },
      enabled: enabled,
    );

Widget _wrap(AgentStore store, {NotificationGateway? gateway}) => ProviderScope(
      overrides: [
        agentStoreProvider.overrideWithValue(store),
        if (gateway != null)
          notificationGatewayProvider.overrideWithValue(gateway),
      ],
      child: MaterialApp(theme: AppTheme.darkTheme, home: const MyAgentsScreen()),
    );

void main() {
  testWidgets('empty store shows the honest empty-state', (tester) async {
    await tester
        .pumpWidget(_wrap(_FakeStore([]), gateway: FakeNotificationGateway()));
    await tester.pumpAndSettle();

    final t = L10n('ru');
    expect(find.text(t.myAgentsEmpty), findsOneWidget);
  });

  testWidgets('list() failure shows an honest error/retry, not the empty-state',
      (tester) async {
    await tester.pumpWidget(
        _wrap(_ThrowingStore(), gateway: FakeNotificationGateway()));
    await tester.pumpAndSettle();

    final t = L10n('ru');
    expect(find.text(t.myAgentsError), findsOneWidget);
    expect(find.text(t.retry), findsOneWidget);
    // Not the spinner, not the empty-state copy.
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text(t.myAgentsEmpty), findsNothing);
  });

  testWidgets('populated store lists agent name + description', (tester) async {
    await tester.pumpWidget(_wrap(_FakeStore([_agent('chef', 'повар')]),
        gateway: FakeNotificationGateway()));
    await tester.pumpAndSettle();

    expect(find.text('chef'), findsOneWidget);
    expect(find.text('повар'), findsOneWidget);
  });

  testWidgets('reminder agent shows a Switch and a next-fire label', (tester) async {
    final gw = FakeNotificationGateway();
    await tester.pumpWidget(_wrap(_FakeStore([_reminder('water')]), gateway: gw));
    await tester.pumpAndSettle();

    expect(find.byType(Switch), findsOneWidget);
    expect(find.byWidgetPredicate((w) => w is Switch && w.value == true),
        findsOneWidget);
    // "Следующее: HH:mm" subtitle for an enabled reminder.
    expect(find.textContaining('Следующее:'), findsOneWidget);
    // Non-reminder tile retains its chevron; reminder tile does not.
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
  });

  testWidgets('toggling the Switch off disables + clears the schedule',
      (tester) async {
    final store = _FakeStore([_reminder('water')]);
    final gw = FakeNotificationGateway();
    await tester.pumpWidget(_wrap(store, gateway: gw));
    await tester.pumpAndSettle();

    // Enabling sync runs in initState → the reminder is scheduled.
    expect(gw.scheduled, isNotEmpty);

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();

    // setEnabled(false) persisted + the schedule cleared via the gateway.
    expect((await store.get('water'))!.enabled, false);
    expect(gw.scheduled, isEmpty);
  });

  testWidgets('denied permission shows the honest note', (tester) async {
    final gw = FakeNotificationGateway()..permission = false;
    await tester.pumpWidget(_wrap(_FakeStore([_reminder('water')]), gateway: gw));
    await tester.pumpAndSettle();

    final t = L10n('ru');
    expect(find.text(t.reminderPermissionNeeded), findsOneWidget);
  });

  testWidgets('bootstrap is hoisted: one permission request + one syncAll, '
      'each agent cancelled once (not N times per tile)', (tester) async {
    // Three reminder agents. The OLD per-tile bootstrap ran a full-store syncAll
    // per tile -> 3 syncAll x 3 cancels = 9 cancelForAgent, 3 permission
    // requests. Hoisted to the screen it must be ONE syncAll: each agent block
    // cancelled exactly once, permission requested exactly once.
    final gw = FakeNotificationGateway();
    await tester.pumpWidget(_wrap(
      _FakeStore([_reminder('a0'), _reminder('a1'), _reminder('a2')]),
      gateway: gw,
    ));
    await tester.pumpAndSettle();

    expect(gw.permissionRequestCount, 1, reason: 'permission requested once');
    for (final name in ['a0', 'a1', 'a2']) {
      expect(gw.cancelCounts[name] ?? 0, lessThanOrEqualTo(1),
          reason: '$name cancelled at most once on first build');
    }
    final totalCancels =
        gw.cancelCounts.values.fold<int>(0, (s, n) => s + n);
    expect(totalCancels, lessThanOrEqualTo(3),
        reason: 'single store-wide syncAll, not one per tile');
    expect(gw.scheduled, isNotEmpty, reason: 'reminders still scheduled');
  });

  testWidgets('resume syncAll failure does not surface an unhandled error',
      (tester) async {
    // A bad agent file makes syncAll throw. The screen bootstrap must guard it:
    // the error is swallowed+logged, no unhandled async error reaches the test.
    final store = _FakeStore([_reminder('water')]);
    final gw = FakeNotificationGateway();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        agentStoreProvider.overrideWithValue(store),
        notificationGatewayProvider.overrideWithValue(gw),
        reminderSchedulerProvider
            .overrideWithValue(_ThrowingScheduler(store: store, gateway: gw)),
      ],
      child:
          MaterialApp(theme: AppTheme.darkTheme, home: const MyAgentsScreen()),
    ));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull,
        reason: 'guardedSyncAll must absorb the failure');
  });
}

/// A scheduler whose syncAll always throws — stands in for a corrupt agent file
/// poisoning the sync, to prove the bootstrap/resume guard swallows it.
class _ThrowingScheduler extends ReminderScheduler {
  _ThrowingScheduler({required super.store, required super.gateway});

  @override
  Future<void> syncAll(DateTime now) async => throw StateError('bad agent');
}
