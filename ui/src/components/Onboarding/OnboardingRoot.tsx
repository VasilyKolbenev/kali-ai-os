import { useOnboardingStore } from "../../stores/onboardingStore";

export function OnboardingRoot() {
  const step = useOnboardingStore((s) => s.currentStep);
  return (
    <div
      data-onboarding="root"
      data-step={step}
      className="w-full h-full flex items-center justify-center"
      style={{ background: "var(--j-bg)", minHeight: "100vh", padding: "var(--j-space-8)" }}
    >
      {/* Step components mount here in Chunks 2-6 */}
      <div style={{ color: "var(--j-text-dim)" }}>onboarding step: {step}</div>
    </div>
  );
}
