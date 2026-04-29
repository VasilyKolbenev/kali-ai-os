import { Mic, Loader2 } from "lucide-react";

export type VoiceOrbState = "idle" | "listening" | "processing";

interface Props {
  state: VoiceOrbState;
  onTap: () => void;
}

export function VoiceOrb({ state, onTap }: Props) {
  const disabled = state === "processing";
  const icon =
    state === "processing" ? (
      <Loader2 size={32} className="animate-spin" />
    ) : (
      <Mic size={32} />
    );
  return (
    <button
      type="button"
      aria-label="Микрофон"
      disabled={disabled}
      onClick={onTap}
      className="voice-orb"
      data-state={state}
      style={{
        width: 96,
        height: 96,
        borderRadius: "50%",
        border: "2px solid var(--j-cyan)",
        background:
          state === "listening"
            ? "rgba(0,224,255,0.18)"
            : "rgba(0,224,255,0.06)",
        boxShadow:
          state === "listening"
            ? "0 0 24px rgba(0,224,255,0.6)"
            : "0 0 8px rgba(0,224,255,0.2)",
        color: "var(--j-cyan)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: disabled ? "default" : "pointer",
        transition: "box-shadow 0.2s, background 0.2s",
        animation: state === "listening" ? "pulse 1.5s infinite" : undefined,
      }}
    >
      {icon}
    </button>
  );
}
