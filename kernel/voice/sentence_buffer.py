"""Streaming sentence aggregator for incremental TTS (P1).

Consumes streamed LLM text deltas and emits *complete* sentences as soon as
they close, so TTS can synthesize sentence 1 while the LLM is still generating
the rest. A sentence closes at terminal punctuation (``. ! ? …``, possibly
repeated) followed by whitespace, or at a newline. Punctuation NOT followed by
whitespace (e.g. the dot in ``3.14``) is not a boundary — that guards decimals
and keeps mid-token deltas from emitting prematurely.

Closed sentences shorter than ``min_chars`` are held and merged with the
following sentence(s) before emission: F5 has a ~2 s fixed cost per call, so a
tiny chunk («Хорошо.») synthesizes slower than it plays back and the voice
audibly gaps at the period. Merging keeps every chunk comfortably ahead of
playback at a negligible time-to-first-audio cost.

See docs/superpowers/plans/2026-06-03-voice-latency-optimization.md.
"""

import re

# Terminal punctuation followed by whitespace, OR a bare newline.
_BOUNDARY = re.compile(r"[.!?…]+\s|\n")

# Below this length a closed sentence is held for merging (F5 per-call
# overhead dominates short chunks — see module docstring).
DEFAULT_MIN_CHARS = 40


class SentenceBuffer:
    """Accumulates text deltas and yields complete, min-length chunks."""

    def __init__(self, min_chars: int = DEFAULT_MIN_CHARS) -> None:
        """Create a buffer.

        Args:
            min_chars: Minimum emitted chunk length; closed sentences are
                merged until the accumulated chunk reaches it. ``0`` emits
                every sentence individually (pre-merge behavior).
        """
        self._buf = ""
        self._closed = ""
        self.min_chars = min_chars

    def feed(self, delta: str) -> list[str]:
        """Add a streamed delta; return any chunks it completed (in order)."""
        self._buf += delta
        out: list[str] = []
        while True:
            match = _BOUNDARY.search(self._buf)
            if match is None:
                break
            end = match.end()
            sentence = self._buf[:end].strip()
            self._buf = self._buf[end:]
            if not sentence:
                continue
            self._closed = f"{self._closed} {sentence}".strip() if self._closed else sentence
            if len(self._closed) >= self.min_chars:
                out.append(self._closed)
                self._closed = ""
        return out

    def flush(self) -> str:
        """Return all remaining text (held sentences + final partial), clear state."""
        remaining = f"{self._closed} {self._buf}".strip()
        self._closed = ""
        self._buf = ""
        return remaining
