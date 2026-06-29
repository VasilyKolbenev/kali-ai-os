/// An agent imported on-device from a shared `kali://import` bundle.
///
/// Immutable. [skillMd] is the full SKILL.md text (used verbatim as the LLM
/// system prompt); [name]/[description] are parsed from its frontmatter.
class ImportedAgent {
  const ImportedAgent({
    required this.name,
    required this.description,
    required this.skillMd,
    required this.installedAt,
  });

  /// Lowercase-latin agent name (the export gate enforces this form).
  final String name;

  /// Human-readable description from the SKILL.md frontmatter.
  final String description;

  /// Full SKILL.md text, used verbatim as the system prompt.
  final String skillMd;

  /// When this agent was imported on-device (UTC).
  final DateTime installedAt;

  /// Serializes to a JSON-compatible map; [installedAt] becomes ISO-8601.
  Map<String, dynamic> toJson() => <String, dynamic>{
        'name': name,
        'description': description,
        'skillMd': skillMd,
        'installedAt': installedAt.toIso8601String(),
      };

  /// Reconstructs an [ImportedAgent] from [toJson] output.
  factory ImportedAgent.fromJson(Map<String, dynamic> json) => ImportedAgent(
        name: json['name'] as String,
        description: json['description'] as String? ?? '',
        skillMd: json['skillMd'] as String,
        installedAt: DateTime.parse(json['installedAt'] as String),
      );
}
