import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/scheduler.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../core/theme.dart';

/// A branded, share-ready agent card rendered to a PNG for the UGC reel hook.
///
/// This is the visual payload shared to TikTok / Reels: agent name, a short
/// description, the install QR (encoding the self-contained `kali://import?...`
/// deep link), an optional creator handle, and KALI branding. It reuses the
/// app's Refined-Futurism theme ([AppTheme]) so the exported image matches the
/// in-app look.
///
/// Sizing is fixed (1080×1350, the 4:5 reel aspect) so the capture is
/// deterministic regardless of the host device — see [captureCardToPngBytes].
class ShareAgentCard extends StatelessWidget {
  /// Logical card width in pixels (the 4:5 reel frame is [cardWidth]×[cardHeight]).
  static const double cardWidth = 1080;

  /// Logical card height in pixels (4:5 aspect — the dominant reel format).
  static const double cardHeight = 1350;

  final String agentName;
  final String agentDescription;

  /// The self-contained deep link burned into the QR (`kali://import?...`).
  final String link;

  /// Optional `@handle` of the creator. Omitted from the card when null/empty.
  final String? creatorHandle;

  /// Localized "scan to install" caption shown under the QR.
  final String scanLabel;

  /// Localized tagline shown in the card header (e.g. the reels caption).
  final String tagline;

  const ShareAgentCard({
    super.key,
    required this.agentName,
    required this.agentDescription,
    required this.link,
    required this.scanLabel,
    required this.tagline,
    this.creatorHandle,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: cardWidth,
      height: cardHeight,
      child: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFF16161B), Color(0xFF08080B)],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
        ),
        child: Stack(
          children: [
            // Soft brand glow behind the header, echoing the share screen.
            Positioned(
              top: -160,
              right: -120,
              child: _glow(AppTheme.primary, 520),
            ),
            Positioned(
              bottom: -200,
              left: -140,
              child: _glow(AppTheme.accent, 460),
            ),
            Padding(
              padding: const EdgeInsets.all(72),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _brandRow(),
                  const SizedBox(height: 56),
                  Text(
                    tagline,
                    style: const TextStyle(
                      color: AppTheme.primary,
                      fontSize: 30,
                      height: 1.3,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 40),
                  Text(
                    agentName,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 72,
                      height: 1.05,
                      fontWeight: FontWeight.bold,
                      letterSpacing: -1,
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    agentDescription,
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 34,
                      height: 1.4,
                    ),
                  ),
                  if (creatorHandle != null && creatorHandle!.isNotEmpty) ...[
                    const SizedBox(height: 28),
                    Text(
                      creatorHandle!.startsWith('@')
                          ? creatorHandle!
                          : '@$creatorHandle',
                      style: const TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 30,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                  const Spacer(),
                  _installRow(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _glow(Color color, double size) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: [color.withValues(alpha: 0.28), Colors.transparent],
        ),
      ),
    );
  }

  Widget _brandRow() {
    return Row(
      children: [
        Container(
          width: 84,
          height: 84,
          decoration: BoxDecoration(
            gradient: AppTheme.primaryGradient,
            borderRadius: BorderRadius.circular(22),
          ),
          child: const Icon(Icons.auto_awesome, color: Colors.black, size: 48),
        ),
        const SizedBox(width: 24),
        const Text(
          'KALI',
          style: TextStyle(
            color: Colors.white,
            fontSize: 44,
            fontWeight: FontWeight.bold,
            letterSpacing: 4,
          ),
        ),
      ],
    );
  }

  Widget _installRow() {
    return Container(
      padding: const EdgeInsets.all(36),
      decoration: BoxDecoration(
        color: AppTheme.glassSurface,
        borderRadius: BorderRadius.circular(36),
        border: Border.all(color: AppTheme.glassBorder, width: 2),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(24),
            ),
            child: QrImageView(
              data: link,
              version: QrVersions.auto,
              size: 220,
              backgroundColor: Colors.white,
              // Disable the embedded gaps/error text so the off-screen render
              // never throws when the link is long (we fall back to text+QR on
              // the screen if a code can't be produced).
              gapless: true,
            ),
          ),
          const SizedBox(width: 36),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  scanLabel,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 38,
                    height: 1.2,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 16),
                const Text(
                  'kali.app',
                  style: TextStyle(
                    color: AppTheme.primary,
                    fontSize: 32,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Renders [card] into the overlay (just off the visible area), paints one
/// frame, then captures it to PNG bytes at [pixelRatio].
///
/// Uses only long-stable public APIs — an [OverlayEntry] keyed with a
/// [GlobalKey], whose [RenderRepaintBoundary] is read back via
/// [RenderRepaintBoundary.toImage]. The entry is positioned at a large offset
/// (`Offstage` keeps it laid out but unpainted to the user) and is always
/// removed in a `finally`, so nothing leaks into the live UI.
///
/// Requires a [BuildContext] with an ancestor [Overlay] (any [MaterialApp] /
/// [Navigator] provides one). Returns the encoded PNG bytes, or `null` if
/// capture/encoding fails — the caller falls back to a text + QR share, never
/// a crash.
Future<Uint8List?> captureCardToPngBytes(
  BuildContext context,
  ShareAgentCard card, {
  double pixelRatio = 3.0,
}) async {
  final overlay = Overlay.maybeOf(context, rootOverlay: true);
  if (overlay == null) return null;

  final boundaryKey = GlobalKey();
  final entry = OverlayEntry(
    builder: (_) => Positioned(
      // Park the card off-screen: laid out and painted into its own layer, but
      // never visible to the user during the brief capture.
      left: -ShareAgentCard.cardWidth * 4,
      top: 0,
      child: RepaintBoundary(
        key: boundaryKey,
        child: Material(
          type: MaterialType.transparency,
          child: card,
        ),
      ),
    ),
  );

  try {
    overlay.insert(entry);
    // Let the overlay build, lay out and paint the card before we read it back.
    await _waitForFrames(2);

    final boundary = boundaryKey.currentContext?.findRenderObject();
    if (boundary is! RenderRepaintBoundary) return null;

    final image = await boundary.toImage(pixelRatio: pixelRatio);
    try {
      final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
      return byteData?.buffer.asUint8List();
    } finally {
      image.dispose();
    }
  } catch (_) {
    // Capture or PNG encode failed — caller falls back to text+QR.
    return null;
  } finally {
    entry.remove();
  }
}

/// Awaits [count] post-frame callbacks so a freshly-inserted overlay child has
/// been laid out and painted before [RenderRepaintBoundary.toImage] reads it.
Future<void> _waitForFrames(int count) async {
  for (var i = 0; i < count; i++) {
    final completer = Completer<void>();
    SchedulerBinding.instance.addPostFrameCallback((_) => completer.complete());
    SchedulerBinding.instance.scheduleFrame();
    await completer.future;
  }
}
