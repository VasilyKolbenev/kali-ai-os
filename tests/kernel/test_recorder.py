"""Tests for audio recorder."""

import numpy as np

from kernel.voice.recorder import AudioChunk, AudioRecorder


class TestAudioChunk:
    def test_create_chunk(self) -> None:
        data = np.zeros(1600, dtype=np.float32)
        chunk = AudioChunk(data=data, sample_rate=16000)
        assert chunk.sample_rate == 16000
        assert chunk.duration_ms == 100.0
        assert len(chunk.data) == 1600

    def test_chunk_duration_calculation(self) -> None:
        data = np.zeros(16000, dtype=np.float32)
        chunk = AudioChunk(data=data, sample_rate=16000)
        assert chunk.duration_ms == 1000.0


class TestAudioRecorder:
    def test_create_recorder(self) -> None:
        recorder = AudioRecorder(sample_rate=16000, chunk_duration_ms=100)
        assert recorder.sample_rate == 16000
        assert recorder.chunk_size == 1600
        assert not recorder.is_recording

    def test_default_params(self) -> None:
        recorder = AudioRecorder()
        assert recorder.sample_rate == 16000
        assert recorder.chunk_size == 512

    def test_recorder_not_recording_by_default(self) -> None:
        recorder = AudioRecorder()
        assert not recorder.is_recording
