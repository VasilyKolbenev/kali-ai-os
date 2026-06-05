"""Streaming sentence aggregator for incremental TTS (P1).

Consumes streamed LLM text deltas and emits *complete* sentences as soon as
they close, so TTS can synthesize sentence 1 while the LLM is still generating
the rest. A sentence closes at terminal punctuation (``. ! ? …``, possibly
repeated) followed by whitespace, or at a newline. Punctuation NOT followed by
whitespace (e.g. the dot in ``3.14``) is not a boundary — that guards decimals
and keeps mid-token deltas from emitting prematurely.

See docs/superpowers/plans/2026-06-03-voice-latency-optimization.md.
"""

import re

# Terminal punctuation followed by whitespace, OR a bare newline.
_BOUNDARY = re.compile(r"[.!?…]+\s|\n")


class SentenceBuffer:
    """Accumulates text deltas and yields complete sentences."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        """Add a streamed delta; return any sentences it completed (in order)."""
        self._buf += delta
        out: list[str] = []
        while True:
            match = _BOUNDARY.search(self._buf)
            if match is None:
                break
            end = match.end()
            sentence = self._buf[:end].strip()
            self._buf = self._buf[end:]
            if sentence:
                out.append(sentence)
        return out

    def flush(self) -> str:
        """Return the remaining buffered text (final partial) and clear it."""
        remaining = self._buf.strip()
        self._buf = ""
        return remaining
