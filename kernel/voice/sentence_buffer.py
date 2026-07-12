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

import os
import re

# Terminal punctuation followed by whitespace, OR a bare newline.
_BOUNDARY = re.compile(r"[.!?…]+\s|\n")

# First-clause fast-path: a comma/semicolon/dash boundary inside the FIRST
# sentence («Конечно, …») can start playing before the sentence even closes.
_CLAUSE_BOUNDARY = re.compile(r"[,;:—]\s")

# Below this length a closed sentence is held for merging (F5 per-call
# overhead dominates short chunks — see module docstring).
DEFAULT_MIN_CHARS = 40

# A clause shorter than this synthesizes to a blip not worth the seam.
MIN_CLAUSE_CHARS = 8


def sentence_buffer_from_env() -> "SentenceBuffer":
    """Buffer configured by KALI_TTS_FIRST_CLAUSE (latency-sprint flag)."""
    return SentenceBuffer(
        first_clause=os.environ.get("KALI_TTS_FIRST_CLAUSE", "0") == "1"
    )


class SentenceBuffer:
    """Accumulates text deltas and yields complete, min-length chunks."""

    def __init__(
        self, min_chars: int = DEFAULT_MIN_CHARS, first_clause: bool = False
    ) -> None:
        """Create a buffer.

        Args:
            min_chars: Minimum emitted chunk length; closed sentences are
                merged until the accumulated chunk reaches it. ``0`` emits
                every sentence individually (pre-merge behavior).
            first_clause: Emit the first clause («Конечно,») of the first
                sentence as its own chunk the moment it appears — trades a
                possible audible seam for earlier first audio. The sentence
                remainder keeps the first-sentence fast-path (threshold 1).
        """
        self._buf = ""
        self._closed = ""
        self.min_chars = min_chars
        self.first_clause = first_clause
        self._clause_emitted = False
        # The very first sentence is emitted as soon as it closes, regardless
        # of min_chars: time-to-first-audio dominates perceived latency, so a
        # short opener («Хорошо.») should reach the speaker immediately while
        # the rest of the reply is still streaming. Merging then resumes for
        # the remaining sentences (no mid-speech gaps).
        self._first_emitted = False

    def feed(self, delta: str) -> list[str]:
        """Add a streamed delta; return any chunks it completed (in order)."""
        self._buf += delta
        out: list[str] = []
        if (
            self.first_clause
            and not self._clause_emitted
            and not self._first_emitted
            and not self._closed
        ):
            match = _CLAUSE_BOUNDARY.search(self._buf)
            if match is not None and match.end() - 1 >= MIN_CLAUSE_CHARS:
                clause = self._buf[: match.end()].strip()
                self._buf = self._buf[match.end():]
                out.append(clause)
                self._clause_emitted = True
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
            threshold = 1 if not self._first_emitted else self.min_chars
            if len(self._closed) >= threshold:
                out.append(self._closed)
                self._closed = ""
                self._first_emitted = True
        return out

    def flush(self) -> str:
        """Return all remaining text (held sentences + final partial), clear state."""
        remaining = f"{self._closed} {self._buf}".strip()
        self._closed = ""
        self._buf = ""
        self._first_emitted = False
        self._clause_emitted = False
        return remaining
