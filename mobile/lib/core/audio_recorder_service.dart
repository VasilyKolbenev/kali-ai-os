import 'dart:async';
import 'dart:convert';
import 'dart:developer';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';
import 'websocket_client.dart';

final audioRecorderProvider = Provider((ref) => AudioRecorderService(ref));

class AudioRecorderService {
  final Ref ref;
  final AudioRecorder _audioRecorder = AudioRecorder();
  StreamSubscription<List<int>>? _audioStreamSub;
  bool _isRecording = false;

  AudioRecorderService(this.ref);

  /// Starts streaming microphone audio to KALI over the WebSocket.
  ///
  /// Returns `true` once capture is running, or `false` if the microphone
  /// permission was denied (the caller should surface this to the user).
  Future<bool> startRecording() async {
    if (_isRecording) return true;

    if (await _audioRecorder.hasPermission()) {
      _isRecording = true;
      final stream = await _audioRecorder.startStream(RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
      ));

      final wsClient = ref.read(wsClientProvider);

      _audioStreamSub = stream.listen((data) {
        if (wsClient.isConnected) {
          final base64Audio = base64Encode(data);
          wsClient.send('voice.audio_stream', {'audio': base64Audio});
        }
      });
      log("Started streaming audio to KALI.", name: 'AudioRecorder');
      return true;
    } else {
      log("Microphone permission denied.", name: 'AudioRecorder');
      return false;
    }
  }

  Future<void> stopRecording() async {
    if (!_isRecording) return;
    await _audioRecorder.stop();
    // Wait for the final chunks (especially on Web) to flush and be sent over WebSocket
    await Future.delayed(const Duration(milliseconds: 300));
    await _audioStreamSub?.cancel();
    _isRecording = false;
    log("Stopped audio streaming.", name: 'AudioRecorder');
  }
}
