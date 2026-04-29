// ui/src/components/VoiceBuilder/__tests__/useRmsVad.test.ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRmsVad } from "../useRmsVad";

describe("useRmsVad", () => {
  it("triggers onSilence after the configured silence duration of low RMS", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();

    const { result } = renderHook(() =>
      useRmsVad({
        threshold: 0.01,
        silenceMs: 1500,
        onSilence,
      }),
    );

    // Push 40 frames of silence (RMS=0). At 50ms each → 2s wall.
    act(() => {
      for (let i = 0; i < 40; i++) {
        result.current.feed(new Float32Array(800).fill(0));
        vi.advanceTimersByTime(50);
      }
    });

    expect(onSilence).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("resets the silence timer on a loud frame", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();

    const { result } = renderHook(() =>
      useRmsVad({ threshold: 0.01, silenceMs: 1500, onSilence }),
    );

    act(() => {
      for (let i = 0; i < 20; i++) {
        result.current.feed(new Float32Array(800).fill(0));
        vi.advanceTimersByTime(50);
      }
      // 1s of silence so far — under threshold
      expect(onSilence).not.toHaveBeenCalled();

      // Loud frame resets
      result.current.feed(new Float32Array(800).fill(0.5));
      vi.advanceTimersByTime(50);

      // More silence — needs a full 1500ms again. With 50ms ticks, the
      // first tick captures silenceStart at delta=0; fire happens when
      // (i-1)*50 >= 1500, i.e., i >= 31. Express the count derivation
      // inline rather than as a magic 31.
      const CHUNK_MS = 50;
      const silenceMs = 1500;
      for (let i = 0; i < Math.floor(silenceMs / CHUNK_MS) + 1; i++) {
        result.current.feed(new Float32Array(800).fill(0));
        vi.advanceTimersByTime(50);
      }
    });

    expect(onSilence).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
