import 'dart:developer';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:just_audio/just_audio.dart';

final audioPlayerProvider = Provider((ref) => AudioPlayerService());

class AudioPlayerService {
  final AudioPlayer _player = AudioPlayer();
  final List<String> _playlistUris = [];
  bool _isPlaying = false;

  AudioPlayerService() {
    _player.playerStateStream.listen((state) {
      if (state.processingState == ProcessingState.completed) {
        _playNext();
      }
    });
  }

  Future<void> queueAudioChunk(String base64Audio) async {
    try {
      // The server now sends a fully-formed WAV file in base64.
      // We can play it directly from memory using a Data URI!
      final dataUri = 'data:audio/wav;base64,$base64Audio';
      _playlistUris.add(dataUri);
      
      if (!_isPlaying) {
        _playNext();
      }
    } catch (e) {
      log("Error queuing audio chunk: $e", name: 'AudioPlayer');
    }
  }

  Future<void> _playNext() async {
    if (_playlistUris.isEmpty) {
      _isPlaying = false;
      return;
    }
    
    _isPlaying = true;
    final uriString = _playlistUris.removeAt(0);
    
    try {
      await _player.setAudioSource(AudioSource.uri(Uri.parse(uriString)));
      await _player.play();
    } catch (e) {
      log("Error playing audio: $e", name: 'AudioPlayer');
      _playNext(); // skip to next on error
    }
  }
  
  Future<void> stop() async {
    await _player.stop();
    _playlistUris.clear();
    _isPlaying = false;
  }
}
