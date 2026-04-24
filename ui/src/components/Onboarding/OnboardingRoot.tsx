import { useOnboardingStore } from "../../stores/onboardingStore";
import { WelcomeStep } from "./steps/WelcomeStep";
import { ApiKeyStep } from "./steps/ApiKeyStep";

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
      {/* Chunks 4-6 add mic-test / first-agent / landing */}
    </div>
  );
}
