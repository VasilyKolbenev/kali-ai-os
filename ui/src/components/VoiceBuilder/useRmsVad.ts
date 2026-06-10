import { useCallback, useRef } from "react";

interface UseRmsVadOptions {
  /** Below this RMS, frames count as silence (0–1 range). Default 0.01. */
  threshold?: number;
  /** Continuous silence for this many ms triggers `onSilence`. Default 1500. */
  silenceMs?: number;
  /** Fired exactly once per silence transition. */
  onSilence: () => void;
}

interface UseRmsVadResult {
  /** Feed a chunk of float32 mono samples. Call as often as audio arrives. */
  feed: (chunk: Float32Array) => void;
  reset: () => void;
}

/**
 * RMS-threshold VAD with a silence-duration timer. Stateless wrt audio
 * (no buffer); the consumer feeds chunks as they're produced and the
 * hook tracks how long the recent RMS has been below threshold.
 *
 * onSilence fires only AFTER at least one above-threshold (speech) frame has
 * been seen — otherwise the timer would arm on the initial pre-speech silence
 * and submit empty audio before the user even starts answering (which read as
 * "voice not recognized"). `reset()` clears the speech flag for the next turn.
 */
export function useRmsVad({
  threshold = 0.01,
  silenceMs = 1500,
  onSilence,
}: UseRmsVadOptions): UseRmsVadResult {
  const silenceStartRef = useRef<number | null>(null);
  const firedRef = useRef(false);
  const hadSpeechRef = useRef(false);

  const feed = useCallback(
    (chunk: Float32Array) => {
      let sumSq = 0;
      for (let i = 0; i < chunk.length; i++) sumSq += chunk[i] * chunk[i];
      const rms = Math.sqrt(sumSq / Math.max(1, chunk.length));

      const now = Date.now();
      if (rms < threshold) {
        if (silenceStartRef.current === null) silenceStartRef.current = now;
        if (
          hadSpeechRef.current &&
          !firedRef.current &&
          now - silenceStartRef.current >= silenceMs
        ) {
          firedRef.current = true;
          onSilence();
        }
      } else {
        hadSpeechRef.current = true;
        silenceStartRef.current = null;
        firedRef.current = false;
      }
    },
    [threshold, silenceMs, onSilence],
  );

  const reset = useCallback(() => {
    silenceStartRef.current = null;
    firedRef.current = false;
    hadSpeechRef.current = false;
  }, []);

  return { feed, reset };
}
