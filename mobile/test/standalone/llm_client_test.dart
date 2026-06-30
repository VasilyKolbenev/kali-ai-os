import 'package:flutter_test/flutter_test.dart';
import 'package:kali_mobile/standalone/llm_client.dart';

class _FakeSettings implements LlmSettings {
  _FakeSettings(this.provider, this.apiKey);

  @override
  final LlmProvider provider;

  @override
  final String? apiKey;
}

void main() {
  test('anthropic reply parsed', () async {
    final client = LlmClient(
      settings: _FakeSettings(LlmProvider.anthropic, 'k'),
      send: (req) async => {
        'content': [
          {'type': 'text', 'text': 'Привет, я повар.'}
        ]
      },
    );
    final r = await client.chat(
      systemPrompt: 'Ты повар',
      history: [ChatMsg.user('привет')],
    );
    expect(r, 'Привет, я повар.');
  });

  test('openai reply parsed', () async {
    final client = LlmClient(
      settings: _FakeSettings(LlmProvider.openai, 'k'),
      send: (req) async => {
        'choices': [
          {
            'message': {'role': 'assistant', 'content': 'Hi from openai.'}
          }
        ]
      },
    );
    final r = await client.chat(
      systemPrompt: 'You are a chef',
      history: [ChatMsg.user('hi')],
    );
    expect(r, 'Hi from openai.');
  });

  test('no key throws LlmError.noKey', () async {
    final client = LlmClient(
      settings: _FakeSettings(LlmProvider.anthropic, null),
      send: (_) async => {},
    );
    expect(
      () => client.chat(systemPrompt: 's', history: const []),
      throwsA(predicate((e) => e is LlmError && e.kind == LlmErrorKind.noKey)),
    );
  });

  test('anthropic request shape: model + system + messages', () async {
    LlmRequest? captured;
    final client = LlmClient(
      settings: _FakeSettings(LlmProvider.anthropic, 'k'),
      send: (req) async {
        captured = req;
        return {
          'content': [
            {'type': 'text', 'text': 'ok'}
          ]
        };
      },
    );
    await client.chat(systemPrompt: 'sys', history: [ChatMsg.user('u')]);
    expect(captured!.url, 'https://api.anthropic.com/v1/messages');
    expect(captured!.headers['x-api-key'], 'k');
    expect(captured!.headers['anthropic-version'], '2023-06-01');
    expect(captured!.body['model'], kAnthropicDefaultModel);
    expect(captured!.body['system'], 'sys');
    expect(captured!.body['messages'], [
      {'role': 'user', 'content': 'u'}
    ]);
  });

  test('openai request shape: system folded into messages', () async {
    LlmRequest? captured;
    final client = LlmClient(
      settings: _FakeSettings(LlmProvider.openai, 'k'),
      send: (req) async {
        captured = req;
        return {
          'choices': [
            {
              'message': {'content': 'ok'}
            }
          ]
        };
      },
    );
    await client.chat(systemPrompt: 'sys', history: [ChatMsg.user('u')]);
    expect(captured!.url, 'https://api.openai.com/v1/chat/completions');
    expect(captured!.headers['Authorization'], 'Bearer k');
    expect(captured!.body['model'], kOpenAiDefaultModel);
    expect(captured!.body['messages'], [
      {'role': 'system', 'content': 'sys'},
      {'role': 'user', 'content': 'u'},
    ]);
  });
}
