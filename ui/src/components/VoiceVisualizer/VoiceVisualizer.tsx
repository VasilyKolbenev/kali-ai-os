import { useEffect, useRef } from "react";
import { useVoiceStore } from "../../stores/voiceStore";

const stateLabels: Record<string, string> = {
  idle: "Ready",
  listening: "Listening...",
  thinking: "Processing...",
  speaking: "Speaking...",
};

const stateColors: Record<string, string> = {
  idle: "var(--j-text-dim)",
  listening: "var(--j-cyan)",
  thinking: "var(--j-amber)",
  speaking: "var(--j-green)",
};

export function VoiceVisualizer() {
  const voiceState = useVoiceStore((s) => s.state);
  const transcript = useVoiceStore((s) => s.transcript);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const audioRef = useRef<{
    ctx: AudioContext;
    analyser: AnalyserNode;
    stream: MediaStream;
  } | null>(null);

  useEffect(() => {
    if (voiceState === "listening") {
      startAudio();
    } else {
      stopAudio();
    }
    return () => stopAudio();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceState]);

  async function startAudio() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);
      audioRef.current = { ctx, analyser, stream };
      draw();
    } catch {
      // Microphone not available — canvas stays blank, state label still shows
    }
  }

  function stopAudio() {
    cancelAnimationFrame(animRef.current);
    if (audioRef.current) {
      audioRef.current.stream.getTracks().forEach((t) => t.stop());
      audioRef.current.ctx.close();
      audioRef.current = null;
    }
  }

  function draw() {
    const canvas = canvasRef.current;
    const audio = audioRef.current;
    if (!canvas || !audio) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const data = new Uint8Array(audio.analyser.frequencyBinCount);
    audio.analyser.getByteFrequencyData(data);

    const w = canvas.width;
    const h = canvas.height;
    const barCount = data.length;
    const barW = w / barCount;

    ctx.clearRect(0, 0, w, h);

    for (let i = 0; i < barCount; i++) {
      const barH = (data[i] / 255) * h;
      const hue = 180 + (i / barCount) * 40; // cyan range
      ctx.fillStyle = `hsla(${hue}, 100%, 60%, 0.8)`;
      ctx.fillRect(i * barW, h - barH, barW - 1, barH);
    }

    animRef.current = requestAnimationFrame(draw);
  }

  const color = stateColors[voiceState] ?? stateColors.idle;

  return (
    <div className="text-center space-y-4 fade-in-up">
      {/* Audio visualization */}
      <div className="w-64 h-12 mx-auto relative">
        {voiceState === "listening" ? (
          <canvas
            ref={canvasRef}
            width={256}
            height={48}
            className="w-full h-full"
          />
        ) : (
          <div className="w-full h-full flex items-end justify-center gap-[2px]">
            {Array.from({ length: 32 }).map((_, i) => (
              <div
                key={i}
                className="w-[6px] rounded-t transition-all duration-300"
                style={{
                  height: voiceState === "speaking"
                    ? `${20 + Math.sin(i * 0.5) * 30}%`
                    : "8%",
                  backgroundColor: voiceState === "idle"
                    ? "rgba(255,255,255,0.1)"
                    : color,
                  opacity: voiceState === "idle" ? 0.3 : 0.7,
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* State label */}
      <div
        className="mono text-xs tracking-[4px] uppercase transition-all duration-500"
        style={{ color }}
      >
        {stateLabels[voiceState] ?? voiceState}
      </div>

      {/* Live transcript */}
      {transcript && (
        <div
          className="text-sm max-w-sm mx-auto leading-relaxed"
          style={{ color: "var(--j-text-dim)" }}
        >
          &ldquo;{transcript}&rdquo;
        </div>
      )}
    </div>
  );
}
