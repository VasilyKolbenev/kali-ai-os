import { useEffect, useRef, useState } from "react";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { useVoiceStore } from "../../../stores/voiceStore";
import { api } from "../../../api/client";
import { FadeSlideUp } from "../../../motion";
import { PulseOrb } from "../../hud";

type MicState = "requesting" | "listening" | "heard" | "denied";

export function MicTestStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const setMic = useOnboardingStore((s) => s.setMicPermission);
  const transcript = useVoiceStore((s) => s.transcript);
  const [state, setState] = useState<MicState>("requesting");
  const advanceRef = useRef(advance);
  advanceRef.current = advance;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
        if (cancelled) return;
        setMic("granted");
        try {
          await api.voiceStart();
        } catch {
          // Voice pipeline may be unavailable (e.g. no backend) — still proceed.
        }
        setState("listening");
      } catch {
        if (!cancelled) {
          setMic("denied");
          setState("denied");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setMic]);

  useEffect(() => {
    if (state === "listening" && transcript && transcript.length > 0) {
      setState("heard");
      const t = setTimeout(() => advanceRef.current(), 1500);
      return () => clearTimeout(t);
    }
  }, [state, transcript]);

  const headline =
    state === "requesting"
      ? "Разрешаю доступ к микрофону..."
      : state === "listening"
        ? "Скажи: «Джарвис, привет»"
        : state === "heard"
          ? "Слышу тебя отлично."
          : "Микрофон не разрешён.";

  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-6 max-w-xl text-center">
        <PulseOrb
          size={64}
          active={state !== "denied"}
          status={state === "heard" ? "success" : "info"}
        />
        <h2 style={{ fontSize: "var(--j-text-xl)", color: "var(--j-text)" }}>
          {headline}
        </h2>
        {transcript && state === "listening" && (
          <div
            style={{
              color: "var(--j-cyan)",
              fontFamily: "var(--j-font-mono)",
              fontSize: "var(--j-text-sm)",
            }}
          >
            {transcript}
          </div>
        )}
        {state === "denied" && (
          <button
            onClick={() => advance()}
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
            }}
          >
            Пропустить — только текст
          </button>
        )}
      </div>
    </FadeSlideUp>
  );
}
