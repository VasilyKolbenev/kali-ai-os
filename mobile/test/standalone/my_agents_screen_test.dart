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
    await tester.pumpWidget(_wrap(_FakeStore([])));
    await tester.pumpAndSettle();

    final t = L10n('ru');
    expect(find.text(t.myAgentsEmpty), findsOneWidget);
  });

  testWidgets('populated store lists agent name + description', (tester) async {
    await tester.pumpWidget(_wrap(_FakeStore([_agent('chef', 'повар')])));
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
}
