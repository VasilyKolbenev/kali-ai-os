import { useOnboardingStore } from "../../stores/onboardingStore";
import { WelcomeStep } from "./steps/WelcomeStep";
import { ApiKeyStep } from "./steps/ApiKeyStep";
import { MicTestStep } from "./steps/MicTestStep";
import { FirstAgentStep } from "./steps/FirstAgentStep";

export function OnboardingRoot() {
  const step = useOnboardingStore((s) => s.currentStep);
  return (
    <div
      data-onboarding="root"
      data-step={step}
      className="w-full h-full flex items-center justify-center"
      style={{ background: "var(--j-bg)", minHeight: "100vh", padding: "var(--j-space-8)" }}
    >
      {step === "welcome" && <WelcomeStep />}
      {step === "api-key" && <ApiKeyStep />}
      {step === "mic-test" && <MicTestStep />}
      {step === "first-agent" && <FirstAgentStep />}
      {/* Chunk 6 adds landing */}
    </div>
  );
}
