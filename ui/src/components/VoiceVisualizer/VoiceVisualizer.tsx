import { useVoiceStore } from "../../stores/voiceStore";

const stateLabels: Record<string, string> = {
  idle: "Ready",
  listening: "Listening...",
  thinking: "Thinking...",
  speaking: "Speaking...",
};

export function VoiceVisualizer() {
  const voiceState = useVoiceStore((s) => s.state);
  const transcript = useVoiceStore((s) => s.transcript);

  return (
    <div className="text-center space-y-3">
      <div className={`text-lg font-medium transition-colors ${
        voiceState === "listening" ? "text-sky-400" :
        voiceState === "thinking" ? "text-orange-400" :
        voiceState === "speaking" ? "text-green-400" : "text-gray-500"
      }`}>
        {stateLabels[voiceState] ?? "Ready"}
      </div>
      {transcript && <div className="text-sm text-gray-400 max-w-md mx-auto italic">&ldquo;{transcript}&rdquo;</div>}
      {voiceState === "listening" && (
        <div className="flex gap-1.5 justify-center">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      )}
    </div>
  );
}
