import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useAudioCapture } from "../useAudioCapture";

describe("useAudioCapture", () => {
  let mediaStream: MediaStream;

  beforeEach(() => {
    mediaStream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;

    (globalThis as any).navigator = (globalThis as any).navigator || {};
    (globalThis.navigator as any).mediaDevices = {
      getUserMedia: vi.fn().mockResolvedValue(mediaStream),
    };

    class FakeMediaRecorder {
      static isTypeSupported = () => true;
      ondataavailable: ((e: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      state = "inactive";
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        const blob = new Blob([new Uint8Array([0, 0, 0, 0])], { type: "audio/webm" });
        this.ondataavailable?.({ data: blob });
        this.onstop?.();
      }
    }
    (globalThis as any).MediaRecorder = FakeMediaRecorder;

    class FakeAnalyser {
      fftSize = 1024;
      getFloatTimeDomainData(target: Float32Array) {
        // Fill with zeros — silent. Test-specific cases override.
        target.fill(0);
      }
    }

    class FakeAudioContext {
      sampleRate = 48000;
      decodeAudioData = vi.fn().mockResolvedValue({
        getChannelData: () => new Float32Array(1600),
        sampleRate: 48000,
        length: 1600,
      });
      createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
      createAnalyser = vi.fn(() => new FakeAnalyser());
      close = vi.fn();
    }
    (globalThis as any).AudioContext = FakeAudioContext;
    (globalThis as any).__FakeAnalyser = FakeAnalyser;
  });

  afterEach(() => {
    delete (globalThis as any).MediaRecorder;
    delete (globalThis as any).AudioContext;
    delete (globalThis as any).__FakeAnalyser;
    vi.useRealTimers();
  });

  it("start() begins capture; stop() yields i16 PCM bytes + sample rate", async () => {
    const { result } = renderHook(() => useAudioCapture());

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.isRecording).toBe(true);

    let captured: { audio: Uint8Array; sample_rate: number } | null = null;
    await act(async () => {
      captured = await result.current.stop();
    });

    expect(captured).not.toBeNull();
    expect(captured!.sample_rate).toBe(48000);
    // 1600 Float32 samples → 1600 i16 samples → 3200 bytes
    expect(captured!.audio.length).toBe(3200);
  });

  it("onFrame is invoked every 50ms during recording", async () => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onFrame }));

    await act(async () => {
      await result.current.start();
    });

    act(() => {
      vi.advanceTimersByTime(160);  // ≥3 polling ticks at 50ms
    });
    expect(onFrame.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(onFrame.mock.calls[0][0]).toBeInstanceOf(Float32Array);

    await act(async () => {
      await result.current.stop();
    });

    const callsBeforeStop = onFrame.mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(200);
    });
    // No further frames after stop().
    expect(onFrame.mock.calls.length).toBe(callsBeforeStop);
  });

  it("permission denied surfaces as a structured error", async () => {
    (globalThis.navigator as any).mediaDevices.getUserMedia = vi
      .fn()
      .mockRejectedValue(new DOMException("denied", "NotAllowedError"));

    const { result } = renderHook(() => useAudioCapture());

    await expect(
      act(async () => {
        await result.current.start();
      }),
    ).rejects.toThrow(/NotAllowedError|denied/);
  });
});
