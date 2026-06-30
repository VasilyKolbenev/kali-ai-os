import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n.dart';
import '../core/theme.dart';
import '../standalone/agent_store.dart';
import '../standalone/imported_agent.dart';
import 'standalone_chat_screen.dart';

/// The on-device [AgentStore]. Overridden in tests with a fake so no native
/// `path_provider` channel is touched.
final agentStoreProvider = Provider<AgentStore>((ref) => FileAgentStore());

/// Lists the agents imported on-device (standalone mode). Tapping one opens a
/// conversation with it via the cloud LLM ([StandaloneChatScreen]).
class MyAgentsScreen extends ConsumerStatefulWidget {
  const MyAgentsScreen({super.key});

  @override
  ConsumerState<MyAgentsScreen> createState() => _MyAgentsScreenState();
}

class _MyAgentsScreenState extends ConsumerState<MyAgentsScreen> {
  late Future<List<ImportedAgent>> _agents;

  @override
  void initState() {
    super.initState();
    _agents = ref.read(agentStoreProvider).list();
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

  Widget _agentTile(BuildContext context, ImportedAgent agent) => Container(
        decoration: BoxDecoration(
          color: AppTheme.glassSurface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppTheme.glassBorder),
        ),
        child: Material(
          type: MaterialType.transparency,
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
        ),
      );
}
