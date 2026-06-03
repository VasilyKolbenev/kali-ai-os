import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:dio/dio.dart';
import 'dart:ui';
import '../core/config.dart';
import '../core/theme.dart';
import '../core/l10n.dart';

class AgentModel {
  final String name;
  final String description;
  bool enabled; // mutable for optimistic updates

  AgentModel({required this.name, required this.description, this.enabled = false});

  factory AgentModel.fromJson(Map<String, dynamic> json, bool isEnabled) {
    return AgentModel(
      name: json['name'] ?? 'Unknown',
      description: json['description'] ?? 'No description',
      enabled: isEnabled,
    );
  }
}

class CatalogEntryModel {
  final String name;
  final String description;
  final String sourceId;
  final String sourceLabel;
  final String trust;

  CatalogEntryModel({
    required this.name,
    required this.description,
    required this.sourceId,
    required this.sourceLabel,
    required this.trust,
  });

  factory CatalogEntryModel.fromJson(Map<String, dynamic> json) {
    return CatalogEntryModel(
      name: json['name'] ?? 'Unknown',
      description: json['description'] ?? 'No description',
      sourceId: json['source_id'] ?? '',
      sourceLabel: json['source_label'] ?? '',
      trust: json['trust'] ?? 'community',
    );
  }
}

class AgentStoreScreen extends ConsumerStatefulWidget {
  const AgentStoreScreen({super.key});

  @override
  ConsumerState<AgentStoreScreen> createState() => _AgentStoreScreenState();
}

class _AgentStoreScreenState extends ConsumerState<AgentStoreScreen> {
  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(
          title: Text(t.agentStoreTitle.toUpperCase(), style: Theme.of(context).textTheme.displayMedium?.copyWith(fontSize: 16, letterSpacing: 3)),
          backgroundColor: Colors.transparent,
          elevation: 0,
          centerTitle: true,
          bottom: TabBar(
            indicatorColor: AppTheme.primary,
            labelColor: AppTheme.primary,
            unselectedLabelColor: AppTheme.textSecondary,
            dividerColor: Colors.white.withValues(alpha: 0.05),
            labelStyle: Theme.of(context).textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.bold),
            tabs: [
              Tab(text: t.installed),
              Tab(text: t.discover),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            _InstalledTab(),
            _DiscoverTab(),
          ],
        ),
      ),
    );
  }
}

class _InstalledTab extends ConsumerStatefulWidget {
  const _InstalledTab();

  @override
  ConsumerState<_InstalledTab> createState() => _InstalledTabState();
}

class _InstalledTabState extends ConsumerState<_InstalledTab> {
  final Dio _dio = Dio();
  List<AgentModel> _agents = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchAgents();
  }

  Future<void> _fetchAgents() async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) return;

    try {
      final allResponse = await _dio.get('http://$ip:3006/agents');
      final runningResponse = await _dio.get('http://$ip:3006/agents/running');

      if (allResponse.statusCode == 200 && runningResponse.statusCode == 200) {
        final List<dynamic> allData = allResponse.data;
        final List<dynamic> runningData = runningResponse.data;
        
        final runningNames = runningData.map((e) => e['name'] as String).toSet();

        setState(() {
          _agents = allData.map((json) {
            final name = json['name'] as String? ?? '';
            return AgentModel.fromJson(json, runningNames.contains(name));
          }).toList();
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _toggleAgent(AgentModel agent, bool value) async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) return;
    final t = L10n.of(ref);

    setState(() {
      agent.enabled = value;
    });

    try {
      final endpoint = value ? 'load' : 'unload';
      final response = await _dio.post('http://$ip:3006/agents/${agent.name}/$endpoint');
      
      if (response.statusCode != 200) {
        setState(() => agent.enabled = !value);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.toggleFailed)));
        }
      }
    } catch (e) {
      setState(() => agent.enabled = !value);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.error(e.toString()))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    if (_isLoading) return const Center(child: CircularProgressIndicator(color: AppTheme.primary));
    if (_error != null) return Center(child: Text(t.error(_error!), style: const TextStyle(color: Colors.redAccent)));
    if (_agents.isEmpty) return Center(child: Text(t.noAgents, style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: AppTheme.textSecondary)));

    return ListView.builder(
      padding: const EdgeInsets.all(16).copyWith(bottom: 100),
      itemCount: _agents.length,
      itemBuilder: (context, index) {
        final agent = _agents[index];
        return Container(
          margin: const EdgeInsets.only(bottom: 16),
          decoration: BoxDecoration(
            color: AppTheme.glassSurface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: agent.enabled ? AppTheme.primary.withValues(alpha: 0.3) : AppTheme.glassBorder),
            boxShadow: agent.enabled ? [
              BoxShadow(
                color: AppTheme.primary.withValues(alpha: 0.1),
                blurRadius: 24,
                spreadRadius: -6,
                offset: const Offset(0, 6),
              )
            ] : null,
          ),
          child: Padding(
            padding: const EdgeInsets.all(20.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Icons.smart_toy_outlined, 
                          color: agent.enabled ? AppTheme.primary : AppTheme.textSecondary
                        ),
                        const SizedBox(width: 12),
                        Text(
                          agent.name,
                          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                            fontSize: 18, 
                            fontWeight: FontWeight.bold,
                            color: agent.enabled ? Colors.white : AppTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                    Switch(
                      value: agent.enabled,
                      onChanged: (val) => _toggleAgent(agent, val),
                      activeColor: AppTheme.primary,
                      activeTrackColor: AppTheme.primary.withValues(alpha: 0.3),
                      inactiveThumbColor: AppTheme.textSecondary,
                      inactiveTrackColor: Colors.white.withValues(alpha: 0.1),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  agent.description,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(height: 1.4),
                ),
              ],
            ),
          ),
        ).animate().fadeIn(delay: Duration(milliseconds: 100 * index)).slideY(begin: 0.1);
      },
    );
  }
}

class _DiscoverTab extends ConsumerStatefulWidget {
  const _DiscoverTab();

  @override
  ConsumerState<_DiscoverTab> createState() => _DiscoverTabState();
}

class _DiscoverTabState extends ConsumerState<_DiscoverTab> {
  final Dio _dio = Dio();
  List<CatalogEntryModel> _catalog = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchCatalog();
  }

  Future<void> _fetchCatalog() async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) return;

    try {
      final response = await _dio.get('http://$ip:3006/skills/catalog');
      if (response.statusCode == 200) {
        final data = response.data['results'] as List<dynamic>;
        setState(() {
          _catalog = data.map((json) => CatalogEntryModel.fromJson(json)).toList();
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _installSkill(CatalogEntryModel skill) async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) return;
    final t = L10n.of(ref);

    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.installing(skill.name))));

    try {
      final response = await _dio.post(
        'http://$ip:3006/skills/install',
        data: {
          'source_id': skill.sourceId,
          'name': skill.name,
        },
      );
      
      if (response.statusCode == 200 && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.installOk(skill.name))));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${t.installFailed}: $e')));
      }
    }
  }

  Color _getTrustColor(String trust) {
    switch (trust.toLowerCase()) {
      case 'official': return Colors.greenAccent;
      case 'verified': return AppTheme.primary;
      default: return AppTheme.textSecondary;
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    if (_isLoading) return const Center(child: CircularProgressIndicator(color: AppTheme.primary));
    if (_error != null) return Center(child: Text(t.error(_error!), style: const TextStyle(color: Colors.redAccent)));
    if (_catalog.isEmpty) return Center(child: Text(t.noCatalog, style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: AppTheme.textSecondary)));

    return ListView.builder(
      padding: const EdgeInsets.all(16).copyWith(bottom: 100),
      itemCount: _catalog.length,
      itemBuilder: (context, index) {
        final skill = _catalog[index];
        final trustColor = _getTrustColor(skill.trust);
        
        return Container(
          margin: const EdgeInsets.only(bottom: 16),
          decoration: BoxDecoration(
            color: AppTheme.glassSurface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: AppTheme.glassBorder),
          ),
          child: Padding(
            padding: const EdgeInsets.all(20.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        skill.name,
                        style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          fontSize: 18, 
                          fontWeight: FontWeight.bold,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.primary.withValues(alpha: 0.15),
                        foregroundColor: AppTheme.primary,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        elevation: 0,
                      ),
                      onPressed: () => _installSkill(skill),
                      child: Text(t.install, style: const TextStyle(fontWeight: FontWeight.bold)),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: trustColor.withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        skill.trust.toUpperCase(),
                        style: TextStyle(
                          color: trustColor, 
                          fontSize: 10, 
                          fontWeight: FontWeight.bold,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Text(
                      skill.sourceLabel,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontSize: 12),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Text(
                  skill.description,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(height: 1.4),
                ),
              ],
            ),
          ),
        ).animate().fadeIn(delay: Duration(milliseconds: 100 * index)).slideY(begin: 0.1);
      },
    );
  }
}
