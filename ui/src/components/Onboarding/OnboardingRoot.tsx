import { useEffect } from "react";
import { useOnboardingStore } from "../../stores/onboardingStore";
import { WelcomeStep } from "./steps/WelcomeStep";
import { ApiKeyStep } from "./steps/ApiKeyStep";
import { ModelsDownloadStep } from "./steps/ModelsDownloadStep";
import { MicTestStep } from "./steps/MicTestStep";
import { ProfileStep } from "./steps/ProfileStep";
import { FirstAgentStep } from "./steps/FirstAgentStep";
import { LandingStep } from "./steps/LandingStep";

export function OnboardingRoot() {
  const step = useOnboardingStore((s) => s.currentStep);
  const skip = useOnboardingStore((s) => s.skip);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        skip();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [skip]);

  return (
    <div
      data-onboarding="root"
      data-step={step}
      className="w-full h-full flex items-center justify-center"
      style={{ background: "var(--j-bg)", minHeight: "100vh", padding: "var(--j-space-8)" }}
    >
      {step === "welcome" && <WelcomeStep />}
      {step === "api-key" && <ApiKeyStep />}
      {step === "models-download" && <ModelsDownloadStep />}
      {step === "mic-test" && <MicTestStep />}
      {step === "profile" && <ProfileStep />}
      {step === "first-agent" && <FirstAgentStep />}
      {step === "landing" && <LandingStep />}
    </div>
  );
}
