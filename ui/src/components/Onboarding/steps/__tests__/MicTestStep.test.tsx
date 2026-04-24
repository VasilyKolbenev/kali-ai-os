import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MicTestStep } from "../MicTestStep";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

vi.mock("../../../../api/client", () => ({
  api: { voiceStart: vi.fn().mockResolvedValue({ status: "started" }) },
}));

function mockGetUserMedia(grant: boolean) {
  const getUserMedia = grant
    ? vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      })
    : vi.fn().mockRejectedValue(new Error("NotAllowedError"));
  Object.defineProperty(navigator, "mediaDevices", {
    writable: true,
    configurable: true,
    value: { getUserMedia },
  });
  return getUserMedia;
}

describe("MicTestStep", () => {
  beforeEach(() => {
    useOnboardingStore.setState({
      currentStep: "mic-test",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
    });
  });

  it("shows denied state when permission refused and offers skip", async () => {
    mockGetUserMedia(false);
    const user = userEvent.setup();
    render(<MicTestStep />);
    await waitFor(() =>
      expect(screen.getByText(/не разрешён/i)).toBeInTheDocument(),
    );
    expect(useOnboardingStore.getState().micPermission).toBe("denied");

    await user.click(screen.getByRole("button", { name: /пропустить/i }));
    expect(useOnboardingStore.getState().currentStep).not.toBe("mic-test");
  });

  it("transitions to listening when permission granted", async () => {
    mockGetUserMedia(true);
    render(<MicTestStep />);
    await waitFor(() =>
      expect(screen.getByText(/джарвис, привет|скажи/i)).toBeInTheDocument(),
    );
    expect(useOnboardingStore.getState().micPermission).toBe("granted");
  });
});
