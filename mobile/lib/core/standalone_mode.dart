import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Whether the app runs without a paired desktop (on-device agents + cloud LLM).
///
/// An explicit flag — NOT inferred from `serverIpProvider == null` — so a user
/// who opens the app but hasn't connected yet is distinguished from one who
/// deliberately chose «Использовать без компьютера». Set true by the connection
/// screen's standalone entry; gates the standalone deep-link import + screens.
final standaloneModeProvider = StateProvider<bool>((ref) => false);
