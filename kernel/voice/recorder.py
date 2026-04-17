"""Microphone audio capture using sounddevice."""

import asyncio
import logging
import queue
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
    """Captures audio from the microphone in async chunks.

    Uses a thread-safe queue.Queue for the sounddevice callback thread,
    bridged to async via a polling loop.
    """

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
        # Thread-safe queue for sounddevice callback thread
        self._thread_queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=300)
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
            self._thread_queue.put_nowait(chunk)
        except queue.Full:
            # Drop oldest chunk to prevent stalling
            try:
                self._thread_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._thread_queue.put_nowait(chunk)
            except queue.Full:
                pass

    async def start(self) -> None:
        if self._recording:
            return
        # Drain any stale chunks from previous session
        while not self._thread_queue.empty():
            try:
                self._thread_queue.get_nowait()
            except queue.Empty:
                break
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
        logger.info(
            "Audio recording started (rate=%d, chunk=%d)", self.sample_rate, self.chunk_size
        )

    async def stop(self) -> None:
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Audio recording stopped")

    async def read_chunk(self) -> AudioChunk:
        """Read next audio chunk, bridging thread-safe queue to async."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                return self._thread_queue.get_nowait()
            except queue.Empty:
                # Yield to event loop briefly, then retry
                await asyncio.sleep(0.005)
