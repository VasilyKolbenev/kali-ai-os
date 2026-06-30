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

class _FakeStore implements AgentStore {
  _FakeStore(this._agents);
  final List<ImportedAgent> _agents;

  @override
  Future<void> save(ImportedAgent agent) async => _agents.add(agent);

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

Widget _wrap(AgentStore store) => ProviderScope(
      overrides: [agentStoreProvider.overrideWithValue(store)],
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
}
