import 'package:dio/dio.dart';

/// Cloud LLM provider for the standalone (BYO-key) chat path.
enum LlmProvider { anthropic, openai }

/// Failure category surfaced to the UI for an honest, actionable message.
enum LlmErrorKind { noKey, network, apiError, quota }

/// Default model ids, matching the desktop router's `DEFAULT_CLOUD_MODELS`
/// (`kernel/models.py`) so mobile and desktop agree on defaults.
const String kAnthropicDefaultModel = 'claude-sonnet-4-20250514';
const String kOpenAiDefaultModel = 'gpt-4.1';

/// Max tokens requested per reply.
const int _maxTokens = 1024;

/// Raised by [LlmClient.chat] on any failure; [kind] drives the UI message.
class LlmError implements Exception {
  LlmError(this.kind, [this.message]);

  final LlmErrorKind kind;
  final String? message;

  @override
  String toString() => 'LlmError(${kind.name}): ${message ?? ''}';
}

/// One chat turn.
class ChatMsg {
  const ChatMsg({required this.role, required this.content});

  /// Convenience for a user turn.
  factory ChatMsg.user(String content) =>
      ChatMsg(role: 'user', content: content);

  /// Convenience for an assistant turn.
  factory ChatMsg.assistant(String content) =>
      ChatMsg(role: 'assistant', content: content);

  /// `'user'` or `'assistant'`.
  final String role;
  final String content;

  Map<String, String> toWire() => {'role': role, 'content': content};
}

/// Provider + key the client needs, abstracted so tests inject a fake instead
/// of touching native secure storage.
abstract class LlmSettings {
  LlmProvider get provider;
  String? get apiKey;
}

/// A fully-formed HTTP request the [LlmClient.send] function should execute.
class LlmRequest {
  const LlmRequest({
    required this.url,
    required this.headers,
    required this.body,
  });

  final String url;
  final Map<String, String> headers;
  final Map<String, dynamic> body;
}

/// Executes an [LlmRequest], returning the decoded JSON response body.
typedef LlmSend = Future<Map<String, dynamic>> Function(LlmRequest request);

/// Cloud LLM client with Anthropic + OpenAI adapters.
///
/// [send] is injectable so unit tests never hit the network or keychain; the
/// production sender wraps `dio` ([dioSender]).
class LlmClient {
  LlmClient({required LlmSettings settings, required LlmSend send})
      : _settings = settings,
        _send = send;

  final LlmSettings _settings;
  final LlmSend _send;

  /// Sends [systemPrompt] + [history] and returns the assistant reply text.
  ///
  /// Throws [LlmError] with the matching [LlmErrorKind] on any failure.
  Future<String> chat({
    required String systemPrompt,
    required List<ChatMsg> history,
  }) async {
    final key = _settings.apiKey;
    if (key == null || key.isEmpty) {
      throw LlmError(LlmErrorKind.noKey);
    }
    final request = switch (_settings.provider) {
      LlmProvider.anthropic => _anthropicRequest(key, systemPrompt, history),
      LlmProvider.openai => _openAiRequest(key, systemPrompt, history),
    };
    final Map<String, dynamic> response;
    try {
      response = await _send(request);
    } on DioException catch (e) {
      throw _mapDioError(e);
    } catch (e) {
      throw LlmError(LlmErrorKind.network, e.toString());
    }
    return _settings.provider == LlmProvider.anthropic
        ? _parseAnthropic(response)
        : _parseOpenAi(response);
  }

  LlmRequest _anthropicRequest(
    String key,
    String systemPrompt,
    List<ChatMsg> history,
  ) =>
      LlmRequest(
        url: 'https://api.anthropic.com/v1/messages',
        headers: {
          'x-api-key': key,
          'anthropic-version': '2023-06-01',
          'content-type': 'application/json',
        },
        body: {
          'model': kAnthropicDefaultModel,
          'max_tokens': _maxTokens,
          'system': systemPrompt,
          'messages': history.map((m) => m.toWire()).toList(),
        },
      );

  LlmRequest _openAiRequest(
    String key,
    String systemPrompt,
    List<ChatMsg> history,
  ) =>
      LlmRequest(
        url: 'https://api.openai.com/v1/chat/completions',
        headers: {
          'Authorization': 'Bearer $key',
          'content-type': 'application/json',
        },
        body: {
          'model': kOpenAiDefaultModel,
          'messages': [
            {'role': 'system', 'content': systemPrompt},
            ...history.map((m) => m.toWire()),
          ],
        },
      );

  String _parseAnthropic(Map<String, dynamic> response) {
    try {
      final content = response['content'] as List<dynamic>;
      return (content.first as Map<String, dynamic>)['text'] as String;
    } catch (_) {
      throw LlmError(LlmErrorKind.apiError, 'unexpected anthropic response');
    }
  }

  String _parseOpenAi(Map<String, dynamic> response) {
    try {
      final choices = response['choices'] as List<dynamic>;
      final message = (choices.first as Map<String, dynamic>)['message']
          as Map<String, dynamic>;
      return message['content'] as String;
    } catch (_) {
      throw LlmError(LlmErrorKind.apiError, 'unexpected openai response');
    }
  }

  LlmError _mapDioError(DioException e) {
    final status = e.response?.statusCode;
    if (status == 429) {
      return LlmError(LlmErrorKind.quota, e.message);
    }
    if (status != null && status >= 400) {
      return LlmError(LlmErrorKind.apiError, e.message);
    }
    return LlmError(LlmErrorKind.network, e.message);
  }
}

/// Production [LlmSend] backed by `dio`.
LlmSend dioSender([Dio? dio]) {
  final client = dio ?? Dio();
  return (request) async {
    final response = await client.post<Map<String, dynamic>>(
      request.url,
      data: request.body,
      options: Options(headers: request.headers),
    );
    return response.data ?? const <String, dynamic>{};
  };
}
