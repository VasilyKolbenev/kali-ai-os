import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:qr_flutter/qr_flutter.dart';
import '../core/config.dart';
import '../core/http_client.dart';
import '../core/l10n.dart';
import '../core/share_config.dart';
import '../core/theme.dart';
import 'widgets/share_agent_card.dart';

/// Share an agent to social apps via the OS native share sheet (no platform
/// OAuth — the user posts under their own account).
///
/// The shared link is a self-contained `kali://import?n=<name>&d=<bundle>`: the
/// agent's exported bundle travels inside the link/QR, so a friend who taps or
/// scans it installs the exact agent with no catalog or server (the P2P import
/// side lives in [DeepLinkHandler]). Above a QR-safe size the link is shown on
/// its own — tapping still works, only the QR is omitted.
class ShareToReelsScreen extends ConsumerStatefulWidget {
  final String agentName;
  final String agentDescription;

  const ShareToReelsScreen({
    super.key,
    required this.agentName,
    required this.agentDescription,
  });

  @override
  ConsumerState<ShareToReelsScreen> createState() => _ShareToReelsScreenState();
}

class _ShareToReelsScreenState extends ConsumerState<ShareToReelsScreen> {
  /// Max link length we still render as a QR (a v40 byte-mode code holds more,
  /// but past this density on-screen scanning gets unreliable).
  static const int _qrMaxChars = 1800;

  String? _link; // kali://import?... once the bundle is fetched
  bool _loading = true;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _prepare();
  }

  Future<void> _prepare() async {
    final ip = ref.read(serverIpProvider);
    if (ip == null) {
      setState(() {
        _loading = false;
        _failed = true;
      });
      return;
    }
    try {
      final url = ServerConfig.api(
          ip, '/skills/${Uri.encodeComponent(widget.agentName)}/export');
      final resp = await ref.read(dioProvider).get(url);
      final body = resp.data as Map<String, dynamic>?;
      final data = body?['data'];
      if (resp.statusCode == 200 && body?['status'] == 'ok' && data is String) {
        final link = Uri(
          scheme: 'kali',
          host: 'import',
          queryParameters: {'n': widget.agentName, 'd': data},
        ).toString();
        setState(() {
          _link = link;
          _loading = false;
        });
      } else {
        setState(() {
          _loading = false;
          _failed = true;
        });
      }
    } catch (_) {
      setState(() {
        _loading = false;
        _failed = true;
      });
    }
  }

  /// Caption posted alongside the reel. Localized copy; the agent name,
  /// description and self-contained link are real.
  String _caption(L10n t) {
    final tags = ShareConfig.defaultHashtags.map((h) => '#$h').join(' ');
    return '${t.reelsCaption}\n\n'
        '🤖 ${widget.agentName} — ${widget.agentDescription}\n\n'
        '📲 ${t.shareLinkLabel}: ${_link ?? ''}\n\n'
        '$tags';
  }

  Future<void> _share(BuildContext context, L10n t) async {
    if (_link == null) return;
    final box = context.findRenderObject() as RenderBox?;
    final origin =
        box != null ? box.localToGlobal(Offset.zero) & box.size : null;

    // Upgrade the payload to a rendered agent-card PNG when we can produce one;
    // otherwise fall back to the original text + (caption-embedded) link share.
    final pngPath = await _renderCardPng(context, t);

    await SharePlus.instance.share(ShareParams(
      text: _caption(t),
      subject: t.shareAgentTitle,
      files: pngPath != null ? [XFile(pngPath)] : null,
      sharePositionOrigin: origin,
    ));
  }

  /// Renders the [ShareAgentCard] to a PNG and writes it to a temp file,
  /// returning the path. Returns null on any failure so [_share] degrades to
  /// the text + link share instead of crashing (honest fallback).
  Future<String?> _renderCardPng(BuildContext context, L10n t) async {
    final link = _link;
    if (link == null) return null;
    try {
      final card = ShareAgentCard(
        agentName: widget.agentName,
        agentDescription: widget.agentDescription,
        link: link,
        scanLabel: t.shareScanToInstall,
        tagline: t.reelsCaption,
      );
      final Uint8List? bytes =
          await captureCardToPngBytes(context, card, pixelRatio: 3.0);
      if (bytes == null || bytes.isEmpty) return null;

      final dir = await getTemporaryDirectory();
      final slug = ShareConfig.slugify(widget.agentName);
      final file = File('${dir.path}/kali_agent_$slug.png');
      await file.writeAsBytes(bytes, flush: true);
      return file.path;
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          Positioned.fill(
            child: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFF16161B), Color(0xFF0F0F13)],
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                ),
              ),
              child: Center(
                child: Container(
                  width: 250,
                  height: 250,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        AppTheme.primary.withValues(alpha: 0.45),
                        Colors.transparent,
                      ],
                    ),
                  ),
                  child: const Icon(Icons.auto_awesome,
                      color: AppTheme.primary, size: 90),
                ),
              ),
            ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.white, size: 28),
                        onPressed: () => Navigator.pop(context),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        t.shareAgentTitle,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Text(
                    widget.agentName,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    widget.agentDescription,
                    style: const TextStyle(
                        color: Colors.white70, fontSize: 14, height: 1.4),
                  ),
                  const SizedBox(height: 20),
                  ..._buildBody(t),
                  const SizedBox(height: 10),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _buildBody(L10n t) {
    if (_loading) {
      return [
        const SizedBox(height: 24),
        Row(
          children: [
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.primary),
            ),
            const SizedBox(width: 14),
            Text(t.shareLoading, style: const TextStyle(color: Colors.white70)),
          ],
        ),
        const SizedBox(height: 40),
      ];
    }
    if (_failed || _link == null) {
      return [
        Text(t.shareExportFailed,
            style: const TextStyle(color: Colors.orangeAccent, fontSize: 14)),
        const SizedBox(height: 40),
      ];
    }

    final link = _link!;
    final showQr = link.length <= _qrMaxChars;
    return [
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: Colors.white.withValues(alpha: 0.15)),
        ),
        child: Row(
          children: [
            if (showQr) ...[
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: QrImageView(
                  data: link,
                  version: QrVersions.auto,
                  size: 84,
                  backgroundColor: Colors.white,
                ),
              ),
              const SizedBox(width: 14),
            ],
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    t.shareScanToInstall,
                    style: const TextStyle(
                        color: Colors.white, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    link,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white54, fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 16),
      Text(
        t.shareSheetHint,
        style: const TextStyle(color: Colors.white60, fontSize: 12, height: 1.4),
      ),
      const SizedBox(height: 16),
      SizedBox(
        width: double.infinity,
        height: 56,
        child: ElevatedButton.icon(
          onPressed: () => _share(context, t),
          icon: const Icon(Icons.ios_share),
          label: Text(
            t.share,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          style: ElevatedButton.styleFrom(
            backgroundColor: AppTheme.primary,
            foregroundColor: Colors.black,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
            elevation: 8,
          ),
        ),
      ),
    ];
  }
}
