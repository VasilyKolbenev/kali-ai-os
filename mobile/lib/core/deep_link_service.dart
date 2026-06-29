import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../presentation/main_screen.dart';
import 'config.dart';
import 'http_client.dart';
import 'l10n.dart';
import 'token_store.dart';
import 'websocket_client.dart';

/// Global messenger key so deep-link results can surface a SnackBar from above
/// any Scaffold (the handler sits at the app root).
final scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

/// Global navigator key so the pairing deep-link can route to the main screen
/// from the app root (the connection screen does this via its own context).
final navigatorKey = GlobalKey<NavigatorState>();

/// Validated `ip` + `token` extracted from a `kali://pair` deep link.
class PairInfo {
  const PairInfo({required this.ip, required this.token});

  final String ip;
  final String token;
}

/// Parses a `kali://pair?ip=<host[:port]>&token=<token>` link into a [PairInfo],
/// or returns `null` for any non-pair / malformed link.
///
/// Validates that both values are present and non-empty and that the host looks
/// like a `host[:port]` (no spaces, parseable as a URI authority). Pure so the
/// parsing can be unit-tested without a Navigator or platform channels.
PairInfo? parsePairLink(Uri uri) {
  if (uri.scheme != 'kali' || uri.host != 'pair') return null;

  final ip = uri.queryParameters['ip']?.trim() ?? '';
  final token = uri.queryParameters['token']?.trim() ?? '';
  if (ip.isEmpty || token.isEmpty) return null;
  if (!_looksLikeHost(ip)) return null;

  return PairInfo(ip: ip, token: token);
}

/// Loose `host[:port]` sanity check — rejects whitespace and unparseable
/// authorities without imposing a strict IP/DNS grammar.
bool _looksLikeHost(String value) {
  if (value.contains(RegExp(r'\s'))) return false;
  final probe = Uri.tryParse('http://$value');
  return probe != null && probe.host.isNotEmpty;
}

/// Persists the paired token and updates the live in-memory holder, so a
/// freshly-scanned token takes effect with no app restart. Pure side effects
/// (no navigation) so it can be unit-tested.
Future<void> applyPairing(
  PairInfo info, {
  required TokenStore store,
  required TokenHolder holder,
}) async {
  await store.saveToken(info.token);
  holder.set(info.token);
}

/// Listens for `kali://import?n=<name>&d=<base64url bundle>` deep links — the
/// import side of the UGC share loop.
///
/// The link is self-contained: the agent bundle travels inside it, so importing
/// needs only a connected backend (`/skills/install-bundle`), no catalog or
/// cloud. Wrap the app with [DeepLinkHandler]; it handles both cold-start links
/// (app launched by the link) and warm links (received while running).
class DeepLinkHandler extends ConsumerStatefulWidget {
  const DeepLinkHandler({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<DeepLinkHandler> createState() => _DeepLinkHandlerState();
}

class _DeepLinkHandlerState extends ConsumerState<DeepLinkHandler> {
  final AppLinks _appLinks = AppLinks();
  StreamSubscription<Uri>? _sub;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final initial = await _appLinks.getInitialLink();
      if (initial != null) _handle(initial);
    } catch (_) {
      // No initial link, or a platform without deep-link support — ignore.
    }
    _sub = _appLinks.uriLinkStream.listen(_handle, onError: (_) {});
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _handle(Uri uri) async {
    final pair = parsePairLink(uri);
    if (pair != null) {
      await _handlePair(pair);
      return;
    }
    await _handleImport(uri);
  }

  /// Persists + holds the paired token, sets the server IP, then connects and
  /// routes into the main screen — the same destination the connection screen
  /// reaches after a successful connect.
  Future<void> _handlePair(PairInfo info) async {
    final holder = ref.read(tokenHolderProvider);
    await applyPairing(info, store: TokenStore(), holder: holder);

    ref.read(serverIpProvider.notifier).state = info.ip;

    final t = L10n.of(ref);
    final messenger = scaffoldMessengerKey.currentState;
    final connected = await ref.read(wsClientProvider).connect(info.ip);
    if (!connected) {
      messenger?.showSnackBar(SnackBar(content: Text(t.pairFailed)));
      return;
    }

    navigatorKey.currentState?.pushReplacement(
      MaterialPageRoute(builder: (_) => const MainScreen()),
    );
  }

  Future<void> _handleImport(Uri uri) async {
    if (uri.scheme != 'kali' || uri.host != 'import') return;
    final data = uri.queryParameters['d'];
    if (data == null || data.isEmpty) return;
    final name = uri.queryParameters['n'];

    final t = L10n.of(ref);
    final messenger = scaffoldMessengerKey.currentState;

    final ip = ref.read(serverIpProvider);
    if (ip == null) {
      messenger?.showSnackBar(SnackBar(content: Text(t.importConnectFirst)));
      return;
    }

    messenger?.showSnackBar(SnackBar(content: Text(t.importInstalling)));
    try {
      final resp = await ref.read(dioProvider).post(
        ServerConfig.api(ip, '/skills/install-bundle'),
        data: {
          'data': data,
          if (name != null && name.isNotEmpty) 'name': name,
          'overwrite': true,
        },
      );
      final body = resp.data as Map<String, dynamic>?;
      final ok = resp.statusCode == 200 && body?['status'] == 'ok';
      messenger?.hideCurrentSnackBar();
      if (ok) {
        final installed = (body?['skill_name'] ?? name ?? '').toString();
        messenger?.showSnackBar(SnackBar(content: Text(t.importOk(installed))));
      } else {
        messenger?.showSnackBar(SnackBar(content: Text(t.importFailed)));
      }
    } catch (_) {
      messenger?.hideCurrentSnackBar();
      messenger?.showSnackBar(SnackBar(content: Text(t.importFailed)));
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
