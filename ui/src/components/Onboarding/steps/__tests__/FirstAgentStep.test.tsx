import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FirstAgentStep } from "../FirstAgentStep";
import { builderApi } from "../../../../api/builder";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

vi.mock("../../../../api/builder", () => ({
  builderApi: {
    start: vi.fn(),
  },
}));

describe("FirstAgentStep", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOnboardingStore.setState({
      currentStep: "first-agent",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
    });
  });

  it("renders 5 skill-template starter chips", () => {
    // Chips must stay within the skill-only builder pilot scope (reminders /
    // trackers / diaries) — non-skill requests used to throw a raw error.
    render(<FirstAgentStep />);
    expect(screen.getByText(/напомни пить воду/i)).toBeInTheDocument();
    expect(screen.getByText(/дневник настроения/i)).toBeInTheDocument();
    expect(screen.getByText(/чашки кофе/i)).toBeInTheDocument();
    expect(screen.getByText(/зарядку/i)).toBeInTheDocument();
    expect(screen.getByText(/перерыв/i)).toBeInTheDocument();
  });

  it("starts builder flow on chip click and stores session id", async () => {
    vi.mocked(builderApi.start).mockResolvedValue({
      session_id: "sess-123",
      question: "Как часто напоминать?",
      total_steps: 3,
      template: null,
    });
    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByText(/напомни пить воду каждые 2 часа/i));
    await waitFor(() =>
      expect(builderApi.start).toHaveBeenCalledWith("напомни пить воду каждые 2 часа"),
    );
    await waitFor(() =>
      expect(useOnboardingStore.getState().firstAgentSession).toBe("sess-123"),
    );
  });

  it("shows a human RU message when builder rejects (no raw errors)", async () => {
    vi.mocked(builderApi.start).mockRejectedValue(new Error("builder offline"));
    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByText(/дневник настроения/i));
    await waitFor(() =>
      expect(screen.getByText(/не получилось создать/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/builder offline/i)).not.toBeInTheDocument();
  });

  it("skip button advances without creating agent", async () => {
    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByRole("button", { name: /пропустить/i }));
    expect(useOnboardingStore.getState().currentStep).not.toBe("first-agent");
  });
});
