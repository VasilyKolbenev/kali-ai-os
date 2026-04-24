import { FadeSlideUp } from "../../../motion";
import { PulseOrb } from "../../hud";
import { useOnboardingStore } from "../../../stores/onboardingStore";

export function WelcomeStep() {
  const advance = useOnboardingStore((s) => s.advance);
  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-8 max-w-xl text-center">
        <div className="relative">
          <PulseOrb size={80} status="info" />
        </div>
        <div
          style={{
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-hud)",
            color: "var(--j-text-dim)",
            textTransform: "uppercase",
          }}
        >
          Инициализация · все системы в норме
        </div>
        <h1
          style={{
            fontSize: "var(--j-text-2xl)",
            color: "var(--j-text)",
            lineHeight: "var(--j-leading-tight)",
            maxWidth: "520px",
          }}
        >
          Я — Jarvis. Помогу превратить твой голос в AI-агентов внутри KALI.
        </h1>
        <p style={{ color: "var(--j-text-dim)", maxWidth: "480px" }}>
          Две минуты — и у тебя будет первый работающий агент.
        </p>
        <button
          onClick={advance}
          style={{
            padding: "var(--j-space-3) var(--j-space-6)",
            background: "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
            border: "1px solid var(--j-border-glow)",
            borderRadius: "var(--j-radius-md)",
            color: "var(--j-cyan)",
            fontFamily: "var(--j-font-mono)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
            cursor: "pointer",
            fontSize: "var(--j-text-sm)",
          }}
        >
          Поехали
        </button>
      </div>
    </FadeSlideUp>
  );
}
