/// Central configuration for the UGC share loop.
///
/// Single source of truth — no share-related URL, store link, or tag is
/// hardcoded anywhere else in the app. To retarget the loop, change it here.
///
/// ## Canonical deep-link format (reconciled — WS-5.7)
/// The shared agent travels **inside the link** as `?n=<name>&d=<base64url
/// bundle>` (self-contained P2P import — no catalog, no server). There are two
/// equivalent carriers for that same payload:
///
///   * **Primary — https Universal/App Link:** `<linkBase>/import?n=&d=`.
///     Auto-linked in social captions (custom schemes are NOT — see the
///     distribution audit §6), opens the installed app directly via Android
///     App Links / iOS Universal Links, and falls back to the landing
///     (OS-detect → store/APK) when the app isn't installed yet.
///   * **Fallback — custom scheme:** `kali://import?n=&d=`. The only scheme
///     registered on-device today (`AndroidManifest.xml` `host="import"`,
///     iOS `CFBundleURLSchemes`); what [DeepLinkHandler] consumes. The landing
///     maps the https form 1:1 back to this, so the payload is identical.
///
/// Producer ([ShareToReelsScreen]), consumer ([DeepLinkHandler]) and the
/// landing all agree on the `n` / `d` param names; the `host`/path segment is
/// `import` in both carriers.
///
/// NOTE (Vasily): set [linkBase] to the real registered domain once chosen —
/// it becomes the Android App Links / iOS Universal Links host. Until then the
/// link is structurally correct (only the host needs swapping); host this
/// page's `/.well-known/assetlinks.json` (Android) + `apple-app-site-association`
/// (iOS) on that domain to make the https form open the app directly.
class ShareConfig {
  ShareConfig._();

  /// Deep-link / landing host for shared agents (https Universal/App Link).
  ///
  /// TODO(Vasily): replace with the real OWNED domain — `kali.app` is a parked
  /// page the project does not own (distribution audit §6). This single
  /// constant is the only place the host is defined.
  static const String linkBase = 'https://kali.app';

  /// Custom-scheme prefix — the on-device fallback carrier (`kali://import`).
  /// Registered in `AndroidManifest.xml` (`host="import"`) and iOS
  /// `CFBundleURLSchemes`. Stays stable even if [linkBase] changes.
  static const String customScheme = 'kali';

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

  /// Canonical **https** share link carrying a self-contained agent bundle:
  /// `<linkBase>/import?n=<name>&d=<base64url bundle>`.
  ///
  /// This is the social-caption-safe form — it auto-links and opens the app
  /// directly (App Links / Universal Links) when installed, or the landing
  /// (deferred install) when not. The landing maps it 1:1 to [customLink].
  static Uri importLink({required String name, required String bundle}) =>
      Uri.parse('$linkBase/import').replace(
        queryParameters: <String, String>{'n': name, 'd': bundle},
      );

  /// The custom-scheme equivalent of [importLink] — `kali://import?n=&d=`.
  /// Identical payload; this is what cold-start / warm deep links deliver to
  /// [DeepLinkHandler] on-device, and the fallback the landing fires.
  static Uri customLink({required String name, required String bundle}) => Uri(
        scheme: customScheme,
        host: 'import',
        queryParameters: <String, String>{'n': name, 'd': bundle},
      );

  /// Legacy slug-only link (`<linkBase>/a/<slug>`) — a *catalog*-resolved form
  /// that predates the self-contained `n=&d=` payload and is not wired into the
  /// live producer. Retained for back-compat; prefer [importLink].
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
