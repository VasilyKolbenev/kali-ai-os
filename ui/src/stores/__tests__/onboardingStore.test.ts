import { describe, it, expect, beforeEach } from "vitest";
import { useOnboardingStore } from "../onboardingStore";

describe("onboardingStore", () => {
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

  it("starts on welcome step", () => {
    expect(useOnboardingStore.getState().currentStep).toBe("welcome");
  });

  it("advances through steps in order", () => {
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
  });

  it("advances mic-test → profile → first-agent", () => {
    useOnboardingStore.setState({ currentStep: "mic-test" });
    useOnboardingStore.getState().advance();
    expect(useOnboardingStore.getState().currentStep).toBe("profile");
    useOnboardingStore.getState().advance();
    expect(useOnboardingStore.getState().currentStep).toBe("first-agent");
  });

  it("completes on final advance from landing", () => {
    useOnboardingStore.setState({ currentStep: "landing" });
    useOnboardingStore.getState().advance();
    expect(useOnboardingStore.getState().completed).toBe(true);
  });

  it("skip() jumps straight to completed", () => {
    useOnboardingStore.getState().skip();
    expect(useOnboardingStore.getState().completed).toBe(true);
  });
});
