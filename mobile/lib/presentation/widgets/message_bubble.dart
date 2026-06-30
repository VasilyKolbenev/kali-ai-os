import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../../core/theme.dart';

/// A single chat turn: [text] from the user or the assistant.
class ChatMessage {
  ChatMessage(this.text, this.isUser);

  final String text;
  final bool isUser;
}

/// A single chat bubble, aligned left (assistant) or right (user).
///
/// Shared by the tethered [ChatScreen] and the standalone agent chat so both
/// render identically. Pure presentation — no provider or network dependency.
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final msg = message;
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
  }
}
