/// An agent imported on-device from a shared `kali://import` bundle.
///
/// Immutable. [skillMd] is the full SKILL.md text (used verbatim as the LLM
/// system prompt); [name]/[description] are parsed from its frontmatter.
/// [template] / [config] carry the voice-built skill type and config for
/// execution (e.g. `template: 'reminder'`). [enabled] and [snoozeUntil]
/// control local scheduling.
class ImportedAgent {
  const ImportedAgent({
    required this.name,
    required this.description,
    required this.skillMd,
    required this.installedAt,
    this.template,
    this.config,
    this.enabled = true,
    this.snoozeUntil,
  });

  /// Agent name validated at the import boundary (lowercase latin, digits, hyphen).
  final String name;

  /// Human-readable description from the SKILL.md frontmatter.
  final String description;

  /// Full SKILL.md text, used verbatim as the system prompt.
  final String skillMd;

  /// When this agent was imported on-device (UTC).
  final DateTime installedAt;

  /// Skill template type, e.g. `'reminder'`. Null for conversational-only agents.
  final String? template;

  /// Raw config map from `skill.yaml`; null if no skill.yaml was present.
  final Map<String, dynamic>? config;

  /// Whether this agent's scheduled features are active. Defaults to true.
  final bool enabled;

  /// If set, scheduling is suppressed until after this time (UTC).
  final DateTime? snoozeUntil;

  /// Returns a copy with the given fields replaced.
  ImportedAgent copyWith({
    bool? enabled,
    DateTime? snoozeUntil,
    bool clearSnooze = false,
  }) =>
      ImportedAgent(
        name: name,
        description: description,
        skillMd: skillMd,
        installedAt: installedAt,
        template: template,
        config: config,
        enabled: enabled ?? this.enabled,
        snoozeUntil: clearSnooze ? null : (snoozeUntil ?? this.snoozeUntil),
      );

  /// Serializes to a JSON-compatible map; [installedAt] becomes ISO-8601.
  Map<String, dynamic> toJson() => <String, dynamic>{
        'name': name,
        'description': description,
        'skillMd': skillMd,
        'installedAt': installedAt.toIso8601String(),
        if (template != null) 'template': template,
        if (config != null) 'config': config,
        'enabled': enabled,
        if (snoozeUntil != null) 'snoozeUntil': snoozeUntil!.toIso8601String(),
      };

  /// Reconstructs an [ImportedAgent] from [toJson] output.
  /// Back-compatible: Increment-1 JSON without new fields loads with safe defaults.
  factory ImportedAgent.fromJson(Map<String, dynamic> json) => ImportedAgent(
        name: json['name'] as String,
        description: json['description'] as String? ?? '',
        skillMd: json['skillMd'] as String,
        installedAt: DateTime.parse(json['installedAt'] as String),
        template: json['template'] as String?,
        config: (json['config'] as Map?)?.cast<String, dynamic>(),
        enabled: json['enabled'] as bool? ?? true,
        snoozeUntil: json['snoozeUntil'] == null
            ? null
            : DateTime.parse(json['snoozeUntil'] as String),
      );
}
