import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WelcomeStep } from "../WelcomeStep";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

describe("WelcomeStep", () => {
  beforeEach(() => {
    useOnboardingStore.setState({
      currentStep: "welcome",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
    });
  });

  it("renders hero copy and CTA", () => {
    render(<WelcomeStep />);
    expect(screen.getByText(/превратить твой голос/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /поехали/i })).toBeInTheDocument();
  });

  it("advances onboarding on CTA click", async () => {
    const user = userEvent.setup();
    render(<WelcomeStep />);
    await user.click(screen.getByRole("button", { name: /поехали/i }));
    expect(useOnboardingStore.getState().currentStep).toBe("api-key");
  });
});
