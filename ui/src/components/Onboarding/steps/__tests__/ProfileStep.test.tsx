import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ProfileStep } from "../ProfileStep";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

const updateProfile = vi.fn().mockResolvedValue({ status: "ok", saved: [] });
const voiceStatus = vi.fn().mockResolvedValue({ models_ready: false });
vi.mock("../../../../api/client", () => ({
  api: {
    updateProfile: (...a: unknown[]) => updateProfile(...a),
    voiceStatus: (...a: unknown[]) => voiceStatus(...a),
  },
}));

beforeEach(() => {
  updateProfile.mockClear();
  useOnboardingStore.setState({ currentStep: "profile", micPermission: "denied" });
});

describe("ProfileStep", () => {
  it("renders all five fields", () => {
    render(<ProfileStep />);
    expect(screen.getByLabelText("Имя")).toBeInTheDocument();
    expect(screen.getByText("Женский")).toBeInTheDocument();
    expect(screen.getByLabelText("Город")).toBeInTheDocument();
    expect(screen.getByText("36-45")).toBeInTheDocument();
    expect(screen.getByText("Строитель")).toBeInTheDocument();
  });

  it("skip advances WITHOUT posting", () => {
    render(<ProfileStep />);
    fireEvent.click(screen.getByText("Пропустить"));
    expect(updateProfile).not.toHaveBeenCalled();
    expect(useOnboardingStore.getState().currentStep).toBe("first-agent");
  });

  it("save posts only filled fields then advances", async () => {
    render(<ProfileStep />);
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Вася" } });
    fireEvent.click(screen.getByText("Женский"));
    fireEvent.click(screen.getByText("Далее"));
    await waitFor(() =>
      expect(updateProfile).toHaveBeenCalledWith({ name: "Вася", gender: "female" }),
    );
    expect(useOnboardingStore.getState().currentStep).toBe("first-agent");
  });

  it("voice buttons hidden when mic denied / stt not ready", () => {
    render(<ProfileStep />);
    expect(screen.queryByLabelText(/сказать голосом/i)).toBeNull();
  });
});
