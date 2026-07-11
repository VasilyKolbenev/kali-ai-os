import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { OnboardingRoot } from "../OnboardingRoot";
import { useOnboardingStore } from "../../../stores/onboardingStore";

vi.mock("../../../api/client", () => ({
  api: {
    testApiKey: vi.fn().mockResolvedValue({ ok: true }),
    updateSettings: vi.fn().mockResolvedValue({}),
    voiceStart: vi.fn().mockResolvedValue({ status: "started" }),
    settings: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("../../../api/builder", () => ({
  builderApi: {
    start: vi.fn().mockResolvedValue({
      session_id: "sess",
      question: "?",
      total_steps: 1,
      template: null,
    }),
  },
}));

describe("Onboarding integration", () => {
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

  it("advance() walks from welcome to landing, final advance completes", () => {
    const { advance } = useOnboardingStore.getState();
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("api-key");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("models-download");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("mic-test");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("profile");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("first-agent");
    advance();
    expect(useOnboardingStore.getState().currentStep).toBe("landing");
    advance();
    expect(useOnboardingStore.getState().completed).toBe(true);
  });

  it("Escape key triggers skip", () => {
    render(<OnboardingRoot />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useOnboardingStore.getState().completed).toBe(true);
  });
});
