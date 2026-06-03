import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:dio/dio.dart';
import 'dart:ui';
import '../core/config.dart';
import '../core/theme.dart';
import '../core/l10n.dart';

class ChatMessage {
  final String text;
  final bool isUser;
  ChatMessage(this.text, this.isUser);
}

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final List<ChatMessage> _messages = [];
  final ScrollController _scrollController = ScrollController();
  bool _isLoading = false;
  
  final Dio _dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
  ));

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    _dio.close();
    super.dispose();
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _sendMessage() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;

    final ip = ref.read(serverIpProvider);
    final t = L10n.of(ref);

    if (ip == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(t.notConnected)),
      );
      return;
    }

    setState(() {
      _messages.add(ChatMessage(text, true));
      _isLoading = true;
    });
    _controller.clear();
    _scrollToBottom();

    try {
      final response = await _dio.post(
        'http://$ip:3006/chat',
        data: {'text': text},
      );
      
      if (response.statusCode == 200) {
        final reply = response.data['response'] ?? "No response";
        setState(() {
          _messages.add(ChatMessage(reply.toString(), false));
        });
        _scrollToBottom();
      }
    } catch (e) {
      setState(() {
        _messages.add(ChatMessage(t.error(e.toString()), false));
      });
      _scrollToBottom();
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(t.chatTitle.toUpperCase(), style: Theme.of(context).textTheme.displayMedium?.copyWith(fontSize: 16, letterSpacing: 3)),
        backgroundColor: Colors.transparent,
        centerTitle: true,
      ),
      body: Stack(
        children: [
          // Background Glow
          Positioned(
            top: 50,
            left: -50,
            child: Container(
              width: 300,
              height: 300,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(
                  colors: [
                    AppTheme.primary.withValues(alpha: 0.14),
                    Colors.transparent,
                  ],
                ),
              ),
            ),
          ).animate().fadeIn(duration: 1000.ms).scale(),

          Column(
            children: [
              Expanded(
                child: _messages.isEmpty 
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.chat_bubble_outline, size: 64, color: AppTheme.textSecondary.withValues(alpha: 0.2)),
                          const SizedBox(height: 16),
                          Text(
                            t.chatEmpty,
                            style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: AppTheme.textSecondary),
                          ),
                        ],
                      ).animate().fadeIn(delay: 300.ms).slideY(begin: 0.2),
                    )
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.only(left: 16, right: 16, top: 16, bottom: 40),
                      itemCount: _messages.length,
                      itemBuilder: (context, index) {
                        final msg = _messages[index];
                        return Align(
                          alignment: msg.isUser ? Alignment.centerRight : Alignment.centerLeft,
                          child: Container(
                            margin: const EdgeInsets.only(bottom: 12),
                            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.75),
                            decoration: BoxDecoration(
                              color: msg.isUser
                                  ? AppTheme.glassSurface
                                  : AppTheme.primary.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.only(
                                topLeft: const Radius.circular(20),
                                topRight: const Radius.circular(20),
                                bottomLeft: Radius.circular(msg.isUser ? 20 : 4),
                                bottomRight: Radius.circular(msg.isUser ? 4 : 20),
                              ),
                              border: Border.all(
                                color: msg.isUser
                                    ? AppTheme.glassBorder
                                    : AppTheme.primary.withValues(alpha: 0.3),
                                width: 1,
                              ),
                              boxShadow: [
                                if (!msg.isUser)
                                  BoxShadow(
                                    color: AppTheme.primary.withValues(alpha: 0.12),
                                    blurRadius: 18,
                                    spreadRadius: -4,
                                    offset: const Offset(0, 6),
                                  )
                              ],
                            ),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                              child: Text(
                                msg.text,
                                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                                  color: Colors.white,
                                  fontWeight: msg.isUser ? FontWeight.normal : FontWeight.w500,
                                ),
                              ),
                            ),
                          ).animate().fadeIn(duration: 300.ms).slideY(begin: 0.1),
                        );
                      },
                    ),
              ),
              
              if (_isLoading)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8.0),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const SizedBox(
                        width: 16, height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.primary),
                      ),
                      const SizedBox(width: 8),
                      Text(t.chatTyping, style: Theme.of(context).textTheme.bodyMedium),
                    ],
                  ).animate().fadeIn(),
                ),
                
              // Input Area
              ClipRRect(
                child: BackdropFilter(
                  filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                  child: Container(
                    padding: const EdgeInsets.all(16).copyWith(bottom: 132 + MediaQuery.of(context).padding.bottom),
                    decoration: BoxDecoration(
                      color: AppTheme.background.withValues(alpha: 0.7),
                      border: Border(top: BorderSide(color: AppTheme.glassBorder)),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _controller,
                            decoration: InputDecoration(
                              hintText: t.chatInputHint,
                              hintStyle: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.white38),
                              filled: true,
                              fillColor: AppTheme.glassSurface,
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(24),
                                borderSide: BorderSide.none,
                              ),
                              contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                            ),
                            onSubmitted: (_) => _sendMessage(),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Container(
                          decoration: BoxDecoration(
                            gradient: AppTheme.primaryGradient,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: AppTheme.primary.withValues(alpha: 0.3),
                                blurRadius: 10,
                                offset: const Offset(0, 2),
                              )
                            ],
                          ),
                          child: IconButton(
                            icon: const Icon(Icons.send_rounded, color: Colors.white, size: 20),
                            onPressed: _sendMessage,
                          ),
                        ).animate().scale(delay: 500.ms),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
