import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/websocket_client.dart';
import 'connection_screen.dart';

class EchoScreen extends ConsumerStatefulWidget {
  const EchoScreen({super.key});

  @override
  ConsumerState<EchoScreen> createState() => _EchoScreenState();
}

class _EchoScreenState extends ConsumerState<EchoScreen> {
  final List<String> _messages = [];
  final TextEditingController _textController = TextEditingController();

  @override
  void initState() {
    super.initState();
    final wsClient = ref.read(wsClientProvider);
    wsClient.onMessage = (data) {
      if (mounted) {
        setState(() {
          _messages.add("KALI: ${data['type']} - ${data['data']}");
        });
      }
    };
  }

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  void _sendMessage() {
    final text = _textController.text.trim();
    if (text.isEmpty) return;

    final wsClient = ref.read(wsClientProvider);
    wsClient.send('ui.command', {'command': 'echo', 'args': text});
    
    setState(() {
      _messages.add("You: $text");
      _textController.clear();
    });
  }

  void _disconnect() {
    ref.read(wsClientProvider).disconnect();
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const ConnectionScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('KALI Link'),
        backgroundColor: Colors.transparent,
        actions: [
          IconButton(
            icon: const Icon(Icons.link_off),
            onPressed: _disconnect,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _messages.length,
              itemBuilder: (context, index) {
                final msg = _messages[index];
                final isKali = msg.startsWith('KALI:');
                return Align(
                  alignment: isKali ? Alignment.centerLeft : Alignment.centerRight,
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    decoration: BoxDecoration(
                      color: isKali ? const Color(0xFF16161B) : const Color(0xFF00D4FF).withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                        color: isKali ? const Color(0xFF2D2D33) : const Color(0xFF00D4FF).withValues(alpha: 0.5),
                      ),
                    ),
                    child: Text(
                      msg,
                      style: TextStyle(
                        color: isKali ? Colors.white : const Color(0xFF00D4FF),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _textController,
                    decoration: InputDecoration(
                      hintText: 'Type a command...',
                      filled: true,
                      fillColor: const Color(0xFF16161B),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(24),
                        borderSide: BorderSide.none,
                      ),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 20),
                    ),
                    onSubmitted: (_) => _sendMessage(),
                  ),
                ),
                const SizedBox(width: 8),
                CircleAvatar(
                  backgroundColor: const Color(0xFF00D4FF),
                  child: IconButton(
                    icon: const Icon(Icons.send, color: Colors.black),
                    onPressed: _sendMessage,
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
