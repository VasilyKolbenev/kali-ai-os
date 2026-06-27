import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config.dart';
import 'http_client.dart';
import 'l10n.dart';

/// Global messenger key so deep-link results can surface a SnackBar from above
/// any Scaffold (the handler sits at the app root).
final scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

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
