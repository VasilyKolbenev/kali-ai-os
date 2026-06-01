import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:ui';
import '../core/l10n.dart';

class ShareToReelsScreen extends ConsumerWidget {
  final String agentName;
  final String agentDescription;

  const ShareToReelsScreen({
    super.key,
    required this.agentName,
    required this.agentDescription,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          // Simulated Video Background
          Positioned.fill(
            child: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFF16161B), Color(0xFF0F0F13)],
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                ),
              ),
              child: Stack(
                children: [
                  // Animated Blob / Avatar Placeholder
                  Center(
                    child: Container(
                      width: 250,
                      height: 250,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: RadialGradient(
                          colors: [
                            const Color(0xFFA855F7).withValues(alpha: 0.5),
                            Colors.transparent,
                          ],
                        ),
                      ),
                    ),
                  ),
                  const Center(
                    child: Icon(Icons.auto_awesome, color: Color(0xFFA855F7), size: 100),
                  ),
                ],
              ),
            ),
          ),

          // Reels UI Overlay
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Top bar
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.white, size: 30),
                        onPressed: () => Navigator.pop(context),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: const Row(
                          children: [
                            Icon(Icons.music_note, color: Colors.white, size: 16),
                            SizedBox(width: 8),
                            Text("Trending Audio", style: TextStyle(color: Colors.white)),
                          ],
                        ),
                      ),
                      const SizedBox(width: 48),
                    ],
                  ),
                  
                  const Spacer(),

                  // Bottom content (TikTok / Reels style)
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      // Text Info & QR Code
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              '@kali_creator',
                              style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              '${t.reelsCaption}\n\n$agentDescription',
                              style: const TextStyle(color: Colors.white, fontSize: 14),
                            ),
                            const SizedBox(height: 12),
                            const Text(
                              '#AI #Jarvis #TechTok #Automation',
                              style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 20),
                            
                            // QR Code Mockup
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.1),
                                borderRadius: BorderRadius.circular(16),
                                border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Container(
                                    width: 60,
                                    height: 60,
                                    decoration: BoxDecoration(
                                      color: Colors.white,
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: const Icon(Icons.qr_code_2, color: Colors.black, size: 40),
                                  ),
                                  const SizedBox(width: 12),
                                  Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(t.reelsDownload, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                                      const Text('KALI Agent Store', style: TextStyle(color: Colors.white54, fontSize: 12)),
                                    ],
                                  )
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      
                      // Right action buttons
                      Column(
                        children: [
                          _buildActionButton(Icons.favorite, '12.4K'),
                          _buildActionButton(Icons.comment, '342'),
                          _buildActionButton(Icons.share, t.share),
                        ],
                      ),
                    ],
                  ),
                  
                  const SizedBox(height: 30),
                  
                  // Big Export Button
                  SizedBox(
                    width: double.infinity,
                    height: 56,
                    child: ElevatedButton(
                      onPressed: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text(t.reelsExporting)),
                        );
                      },
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF00D4FF),
                        foregroundColor: Colors.black,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
                        elevation: 8,
                      ),
                      child: Text(
                        t.reelsPublish,
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildActionButton(IconData icon, String label) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(
        children: [
          Icon(icon, color: Colors.white, size: 36),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: Colors.white, fontSize: 12)),
        ],
      ),
    );
  }
}
