import { useCallback, useRef, useState } from "react";

interface UseAudioCaptureOptions {
  /**
   * Called every ~50ms during recording with the latest Float32 frame
   * from the AnalyserNode (typically `fftSize` samples = 1024). Use for
   * VAD or live visualisations. Optional — the hook also works as a
   * pure record-and-blob primitive without it.
   */
  onFrame?: (frame: Float32Array) => void;
}

interface UseAudioCaptureResult {
  start: () => Promise<void>;
  stop: () => Promise<{ audio: Uint8Array; sample_rate: number } | null>;
  isRecording: boolean;
}

const POLL_MS = 50;
const FFT_SIZE = 1024;

/**
 * Browser audio capture for the voice-builder pilot.
 *
 * Two parallel paths off one MediaStream:
 * - MediaRecorder (webm/opus) → on stop(), decode to Float32 → Int16 LE
 *   → return as Uint8Array. This is what we send to /voice/transcribe.
 * - AnalyserNode polled every 50ms → onFrame(Float32) callback. This
 *   feeds the RMS-VAD so the pilot can auto-stop on silence without
 *   waiting for the recorder's blob.
 *
 * The Int16 conversion is symmetric (multiply by 32767 in both
 * directions) to match the bridge worker's symmetric divide-by-32768
 * decode in tts_worker.py:161 — same convention round-trip.
 */
export function useAudioCapture(opts: UseAudioCaptureOptions = {}): UseAudioCaptureResult {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const pollerRef = useRef<number | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const onFrameRef = useRef(opts.onFrame);
  onFrameRef.current = opts.onFrame;
  const [isRecording, setIsRecording] = useState(false);

  const start = useCallback(async () => {
    // Reset chunks BEFORE the try so stale data never carries into next attempt.
    chunksRef.current = [];

    let stream: MediaStream | null = null;
    let audioCtx: AudioContext | null = null;
    let pollerId: number | null = null;

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Live frame tap for VAD.
      audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = FFT_SIZE;
      source.connect(analyser);
      analyserRef.current = analyser;

      const buf = new Float32Array(analyser.fftSize);
      pollerId = window.setInterval(() => {
        analyserRef.current?.getFloatTimeDomainData(buf);
        // I2 fix: pass a fresh copy so consumers can hold the reference safely
        // across ticks without seeing it overwritten by the next poll.
        onFrameRef.current?.(new Float32Array(buf));
      }, POLL_MS);
      pollerRef.current = pollerId;

      // Blob path for the eventual /voice/transcribe payload.
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.start();
      recorderRef.current = recorder;
      setIsRecording(true);
    } catch (e) {
      // C2 fix: cleanup partial init in reverse order before re-throwing.
      if (pollerId !== null) window.clearInterval(pollerId);
      pollerRef.current = null;
      if (audioCtx) audioCtx.close();
      audioCtxRef.current = null;
      analyserRef.current = null;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      recorderRef.current = null;
      throw e;
    }
  }, []);

  const stop = useCallback(async () => {
    // 1. Always clear poller first.
    if (pollerRef.current !== null) {
      window.clearInterval(pollerRef.current);
      pollerRef.current = null;
    }

    // 2. Capture refs locally, then null them out so re-entry sees null.
    const recorder = recorderRef.current;
    const stream = streamRef.current;
    recorderRef.current = null;
    streamRef.current = null;

    if (!recorder) {
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
      analyserRef.current = null;
      return null;
    }

    // 3. C1 fix: only call stop()+await if recorder is actually active.
    // Calling recorder.stop() when state === "inactive" throws InvalidStateError.
    // If already inactive, the onstop event has already fired and assigning a new
    // onstop handler will NOT re-fire it — the promise would hang forever.
    if (recorder.state !== "inactive") {
      const stopped = new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
      });
      recorder.stop();
      await stopped;
    }

    stream?.getTracks().forEach((t) => t.stop());
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    analyserRef.current = null;
    setIsRecording(false);

    const webmBlob = new Blob(chunksRef.current, { type: "audio/webm" });
    const arrayBuffer = await webmBlob.arrayBuffer();
    const decodeCtx = new AudioContext();
    const decoded = await decodeCtx.decodeAudioData(arrayBuffer);
    const sample_rate = decoded.sampleRate;
    // I1 fix: copy before closing context — getChannelData returns a view into
    // the AudioBuffer's internal storage which may be invalidated by close().
    const float32 = new Float32Array(decoded.getChannelData(0));
    decodeCtx.close();

    // Float32 [-1, 1] → Int16 LE — symmetric scaling to match
    // tts_worker.py:161 which divides by 32768.0 in both directions.
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const clamped = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = Math.round(clamped * 32767);
    }
    const audio = new Uint8Array(int16.buffer);

    return { audio, sample_rate };
  }, []);

  return { start, stop, isRecording };
}
