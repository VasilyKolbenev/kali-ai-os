import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n.dart';
import '../core/theme.dart';
import '../standalone/imported_agent.dart';
import '../standalone/llm_client.dart';
import '../standalone/llm_settings_store.dart';
import 'llm_settings_screen.dart';
import 'widgets/message_bubble.dart';

/// Sends a system prompt + history to a cloud LLM and returns the reply.
///
/// Abstracted so widget tests inject a fake (no network / no keychain). The
/// production implementation loads BYO settings and calls [LlmClient].
typedef ChatFn = Future<String> Function({
  required String systemPrompt,
  required List<ChatMsg> history,
});

/// Production [ChatFn]: loads BYO settings, then delegates to [LlmClient].
/// Overridden in tests with a fake reply / error.
final chatFnProvider = Provider<ChatFn>((ref) {
  return ({required systemPrompt, required history}) async {
    final settings = await LlmSettingsStore().load();
    final client = LlmClient(settings: settings, send: dioSender());
    return client.chat(systemPrompt: systemPrompt, history: history);
  };
});

/// A thin chat with an [ImportedAgent]: the agent's SKILL.md is the system
/// prompt, and turns go to the cloud LLM via [chatFnProvider]. Honest failure —
/// a missing key surfaces a CTA to settings; other errors render inline.
class StandaloneChatScreen extends ConsumerStatefulWidget {
  const StandaloneChatScreen({super.key, required this.agent});

  final ImportedAgent agent;

  @override
  ConsumerState<StandaloneChatScreen> createState() => _StandaloneChatScreenState();
}

class _StandaloneChatScreenState extends ConsumerState<StandaloneChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<ChatMessage> _messages = [];
  bool _isLoading = false;
  bool _needsKey = false;

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
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

  /// Max prior turns sent to the model per request. The full thread stays on
  /// screen, but only the last [_historyCap] turns go over the wire — bounding
  /// token cost/latency on the user's BYO key (a long chat otherwise resends
  /// everything each turn).
  static const int _historyCap = 20;

  List<ChatMsg> _history() {
    final recent = _messages.length > _historyCap
        ? _messages.sublist(_messages.length - _historyCap)
        : _messages;
    return recent
        .map((m) => m.isUser ? ChatMsg.user(m.text) : ChatMsg.assistant(m.text))
        .toList();
  }

  void _clearChat() => setState(() {
        _messages.clear();
        _needsKey = false;
      });

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isLoading) return;

    setState(() {
      _messages.add(ChatMessage(text, true));
      _isLoading = true;
      _needsKey = false;
    });
    _controller.clear();
    _scrollToBottom();

    final chat = ref.read(chatFnProvider);
    final t = L10n.of(ref);
    try {
      final reply = await chat(
        systemPrompt: widget.agent.skillMd,
        history: _history(),
      );
      if (!mounted) return; // back-nav mid-request: don't setState after dispose
      setState(() => _messages.add(ChatMessage(reply, false)));
    } on LlmError catch (e) {
      if (!mounted) return;
      if (e.kind == LlmErrorKind.noKey) {
        setState(() => _needsKey = true);
      } else {
        setState(() => _messages.add(ChatMessage(_errorText(t, e.kind), false)));
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _messages.add(ChatMessage(t.llmErrorNetwork, false)));
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
        _scrollToBottom();
      }
    }
  }

  String _errorText(L10n t, LlmErrorKind kind) => switch (kind) {
        LlmErrorKind.network => t.llmErrorNetwork,
        LlmErrorKind.quota => t.llmErrorQuota,
        LlmErrorKind.apiError => t.llmErrorApi,
        LlmErrorKind.noKey => t.llmAddKeyCta,
      };

  @override
  Widget build(BuildContext context) {
    final t = L10n.of(ref);

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: Text(
          widget.agent.name.toUpperCase(),
          style: Theme.of(context).textTheme.displayMedium?.copyWith(fontSize: 16, letterSpacing: 3),
        ),
        backgroundColor: Colors.transparent,
        centerTitle: true,
        actions: [
          if (_messages.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.delete_outline_rounded),
              tooltip: t.chatClear,
              onPressed: _clearChat,
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty
                ? Center(
                    child: Text(
                      t.chatEmpty,
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: AppTheme.textSecondary),
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) => MessageBubble(message: _messages[index]),
                  ),
          ),
          if (_needsKey) _addKeyCta(t),
          if (_isLoading)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.primary)),
                  const SizedBox(width: 8),
                  Text(t.chatTyping, style: Theme.of(context).textTheme.bodyMedium),
                ],
              ),
            ),
          _inputBar(t),
        ],
      ),
    );
  }

  Widget _addKeyCta(L10n t) => Padding(
        padding: const EdgeInsets.all(16),
        child: ElevatedButton.icon(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const LlmSettingsScreen()),
          ),
          icon: const Icon(Icons.key_rounded, color: Colors.black),
          label: Text(t.llmAddKeyCta, style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
          style: ElevatedButton.styleFrom(
            backgroundColor: AppTheme.primary,
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          ),
        ),
      );

  Widget _inputBar(L10n t) => Container(
        padding: const EdgeInsets.all(16),
        decoration: const BoxDecoration(
          color: AppTheme.background,
          border: Border(top: BorderSide(color: AppTheme.glassBorder)),
        ),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                decoration: InputDecoration(
                  hintText: t.chatInputHint,
                  filled: true,
                  fillColor: AppTheme.glassSurface,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                ),
                onSubmitted: (_) => _send(),
              ),
            ),
            const SizedBox(width: 12),
            Container(
              decoration: const BoxDecoration(gradient: AppTheme.primaryGradient, shape: BoxShape.circle),
              child: IconButton(
                icon: const Icon(Icons.send_rounded, color: Colors.white, size: 20),
                onPressed: _send,
              ),
            ),
          ],
        ),
      );
}
