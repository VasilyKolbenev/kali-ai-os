"""Microphone audio capture using sounddevice."""

import asyncio
import logging
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A chunk of audio data with metadata."""

    data: np.ndarray
    sample_rate: int

    @property
    def duration_ms(self) -> float:
        """Duration of this chunk in milliseconds."""
        return len(self.data) / self.sample_rate * 1000


class AudioRecorder:
    """Captures audio from the microphone in async chunks."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 32,
        device: int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)
        self._device = device
        self._stream: sd.InputStream | None = None
        self._queue: asyncio.Queue[AudioChunk] = asyncio.Queue()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("Audio callback status: %s", status)
        chunk = AudioChunk(
            data=indata[:, 0].copy().astype(np.float32),
            sample_rate=self.sample_rate,
        )
        try:
            self._queue.put_nowait(chunk)
        except asyncio.QueueFull:
            logger.warning("Audio queue full, dropping chunk")

    async def start(self) -> None:
        if self._recording:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            device=self._device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._recording = True
        logger.info("Audio recording started (rate=%d, chunk=%d)", self.sample_rate, self.chunk_size)

    async def stop(self) -> None:
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Audio recording stopped")

    async def read_chunk(self) -> AudioChunk:
        return await self._queue.get()
