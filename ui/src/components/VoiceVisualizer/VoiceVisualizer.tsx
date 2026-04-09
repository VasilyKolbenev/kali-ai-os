import { useVoiceStore } from "../../stores/voiceStore";

const stateConfig: Record<string, { label: string; color: string; glow: string }> = {
  idle: { label: "Ready", color: "var(--j-text-dim)", glow: "none" },
  listening: { label: "Listening", color: "var(--j-cyan)", glow: "0 0 20px rgba(0, 212, 255, 0.15)" },
  thinking: { label: "Processing", color: "var(--j-amber)", glow: "0 0 20px rgba(255, 184, 0, 0.15)" },
  speaking: { label: "Speaking", color: "var(--j-green)", glow: "0 0 20px rgba(0, 230, 118, 0.15)" },
};

export function VoiceVisualizer() {
  const voiceState = useVoiceStore((s) => s.state);
  const transcript = useVoiceStore((s) => s.transcript);
  const config = stateConfig[voiceState] ?? stateConfig.idle;

  return (
    <div className="text-center space-y-4 fade-in-up">
      {/* Audio waveform bars */}
      {voiceState === "listening" && (
        <div className="flex gap-[3px] justify-center items-end h-6">
          {Array.from({ length: 12 }).map((_, i) => (
            <div
              key={i}
              className="w-[2px] rounded-full"
              style={{
                background: "var(--j-cyan)",
                height: `${8 + Math.sin(i * 0.8) * 14}px`,
                opacity: 0.4 + Math.sin(i * 0.5) * 0.3,
                animation: `waveBar 1.2s ease-in-out ${i * 0.08}s infinite alternate`,
              }}
            />
          ))}
        </div>
      )}

      {/* State label */}
      <div className="mono text-xs tracking-[4px] uppercase transition-all duration-500"
        style={{ color: config.color, textShadow: config.glow }}>
        {config.label}
      </div>

      {/* Transcript */}
      {transcript && (
        <div className="text-sm max-w-sm mx-auto leading-relaxed"
          style={{ color: "var(--j-text-dim)" }}>
          &ldquo;{transcript}&rdquo;
        </div>
      )}

      <style>{`
        @keyframes waveBar {
          0% { transform: scaleY(1); }
          100% { transform: scaleY(2.5); }
        }
      `}</style>
    </div>
  );
}
