import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiKeyStep } from "../ApiKeyStep";
import { api } from "../../../../api/client";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

vi.mock("../../../../api/client", () => ({
  api: {
    testApiKey: vi.fn(),
    updateSettings: vi.fn().mockResolvedValue({}),
  },
}));

describe("ApiKeyStep", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOnboardingStore.setState({
      currentStep: "api-key",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
    });
  });

  it("renders 4 provider cards", () => {
    render(<ApiKeyStep />);
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek")).toBeInTheDocument();
  });

  it("validates API key via test endpoint and advances on success", async () => {
    const user = userEvent.setup();
    vi.mocked(api.testApiKey).mockResolvedValue({ ok: true });
    render(<ApiKeyStep />);
    await user.click(screen.getByText("OpenAI"));
    const input = screen.getByPlaceholderText("sk-...");
    await user.type(input, "sk-test-valid");
    await user.click(screen.getByRole("button", { name: /проверить/i }));
    await waitFor(() =>
      expect(api.testApiKey).toHaveBeenCalledWith("openai", "sk-test-valid"),
    );
    await waitFor(() => expect(useOnboardingStore.getState().apiKeyValid).toBe(true));
  });

  it("shows error on invalid key", async () => {
    const user = userEvent.setup();
    vi.mocked(api.testApiKey).mockResolvedValue({
      ok: false,
      error: "unauthorized",
    });
    render(<ApiKeyStep />);
    await user.click(screen.getByText("OpenAI"));
    await user.type(screen.getByPlaceholderText("sk-..."), "bad");
    await user.click(screen.getByRole("button", { name: /проверить/i }));
    await waitFor(() =>
      expect(screen.getByText(/unauthorized/i)).toBeInTheDocument(),
    );
  });

  it("skip path marks apiKeyValid=false and advances", async () => {
    const user = userEvent.setup();
    render(<ApiKeyStep />);
    await user.click(screen.getByRole("button", { name: /пропустить/i }));
    expect(useOnboardingStore.getState().apiKeyValid).toBe(false);
    expect(useOnboardingStore.getState().currentStep).not.toBe("api-key");
  });
});
