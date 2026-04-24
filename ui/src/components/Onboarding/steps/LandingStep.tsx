import { useEffect } from "react";
import { api } from "../../../api/client";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { FadeSlideUp } from "../../../motion";
import { PulseOrb } from "../../hud";

export function LandingStep() {
  const advance = useOnboardingStore((s) => s.advance);

  useEffect(() => {
    // Persist the completion flag, then flip the store so the App gate closes.
    let cancelled = false;
    api
      .updateSettings({ onboarding_completed: true })
      .catch(() => {
        // Persistence failure is not blocking — UI state still advances and
        // next boot will re-attempt gate resolution.
      })
      .finally(() => {
        if (cancelled) return;
        const t = setTimeout(() => advance(), 1600);
        return () => clearTimeout(t);
      });
    return () => {
      cancelled = true;
    };
  }, [advance]);

  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-6 max-w-xl text-center">
        <PulseOrb size={96} status="success" />
        <h2
          style={{
            fontSize: "var(--j-text-2xl)",
            color: "var(--j-text)",
            lineHeight: "var(--j-leading-tight)",
          }}
        >
          Добро пожаловать домой.
        </h2>
        <p style={{ color: "var(--j-text-dim)", maxWidth: "420px" }}>
          Говори или пиши — я рядом. Создавай новых агентов в любой момент.
        </p>
      </div>
    </FadeSlideUp>
  );
}
