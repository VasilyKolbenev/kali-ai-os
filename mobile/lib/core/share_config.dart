/// Central configuration for the UGC share loop.
///
/// Single source of truth — no share-related URL, store link, or tag is
/// hardcoded anywhere else in the app. To retarget the loop, change it here.
///
/// NOTE (Vasily): set [linkBase] to the real registered domain once chosen —
/// it becomes the Android App Links / iOS Universal Links host that resolves a
/// shared agent (Slice 2). Until then the link is structurally correct and the
/// QR encodes it faithfully; only the host needs swapping.
class ShareConfig {
  ShareConfig._();

  /// Deep-link / landing host for shared agents. Replace with the real domain.
  static const String linkBase = 'https://kali.app';

  /// Store links for the install CTA (placeholders until the app is published).
  static const String androidStoreUrl =
      'https://play.google.com/store/apps/details?id=ai.kali.mobile';
  static const String iosStoreUrl = 'https://apps.apple.com/app/kali';

  /// Default discovery hashtags appended to a shared caption.
  static const List<String> defaultHashtags = <String>[
    'KALI',
    'AI',
    'Jarvis',
  ];

  /// Canonical deep link for a given agent slug — `<linkBase>/a/<slug>`.
  ///
  /// This is the link burned into the QR and the share caption. It resolves to
  /// a one-tap install once the landing + import handler land (Slice 2).
  static Uri agentLink(String slug) => Uri.parse('$linkBase/a/$slug');

  /// Turn an agent name into a stable, URL-safe slug.
  ///
  /// ASCII letters/digits are kept; spaces and separators collapse to a single
  /// hyphen. Names with no ASCII content (e.g. Cyrillic-only) fall back to a
  /// deterministic content hash so the same agent always maps to the same link.
  static String slugify(String name) {
    final buffer = StringBuffer();
    for (final code in name.trim().toLowerCase().runes) {
      final ch = String.fromCharCode(code);
      if (RegExp(r'[a-z0-9]').hasMatch(ch)) {
        buffer.write(ch);
      } else if (ch == ' ' || ch == '-' || ch == '_') {
        buffer.write('-');
      }
    }
    final ascii = buffer
        .toString()
        .replaceAll(RegExp(r'-+'), '-')
        .replaceAll(RegExp(r'^-|-$'), '');
    if (ascii.isNotEmpty) return ascii;
    return 'agent-${_fnv1a(name).toRadixString(16)}';
  }

  /// FNV-1a 32-bit hash — deterministic across runs/platforms (unlike
  /// `String.hashCode`), so a slug is stable for a given name.
  static int _fnv1a(String input) {
    var hash = 0x811c9dc5;
    for (final unit in input.codeUnits) {
      hash ^= unit;
      hash = (hash * 0x01000193) & 0xffffffff;
    }
    return hash;
  }
}
