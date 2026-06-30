/// Shared allowlist for agent names: lowercase latin letters, digits, hyphen.
///
/// Used by both [bundle_importer.dart] (validated at the untrusted-input
/// boundary) and [agent_store.dart] (enforced again at persistence).
final RegExp kSafeAgentName = RegExp(r'^[a-z0-9-]+$');
