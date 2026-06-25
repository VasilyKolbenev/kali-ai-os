import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FirstAgentStep } from "../FirstAgentStep";
import { builderApi } from "../../../../api/builder";
import { useOnboardingStore } from "../../../../stores/onboardingStore";

vi.mock("../../../../api/builder", () => ({
  builderApi: {
    extract: vi.fn(),
    deploy: vi.fn(),
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
    render(<FirstAgentStep />);
    expect(screen.getByText(/напомни пить воду/i)).toBeInTheDocument();
    expect(screen.getByText(/дневник настроения/i)).toBeInTheDocument();
    expect(screen.getByText(/чашки кофе/i)).toBeInTheDocument();
    expect(screen.getByText(/зарядку/i)).toBeInTheDocument();
    expect(screen.getByText(/перерыв/i)).toBeInTheDocument();
  });

  it("complete extract → actually deploys the agent and stores the session", async () => {
    vi.mocked(builderApi.extract).mockResolvedValue({
      complete: true,
      session_id: "sess-123",
      spec: { name: "voda", description: "пить воду", type: "skill", template: "tracker", config: {} },
    } as never);
    vi.mocked(builderApi.deploy).mockResolvedValue({ status: "deployed", name: "voda" });

    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByText(/напомни пить воду каждые 2 часа/i));

    await waitFor(() =>
      expect(builderApi.extract).toHaveBeenCalledWith("напомни пить воду каждые 2 часа"),
    );
    // The fix: it deploys for real (it never did) and stores the session.
    await waitFor(() => expect(builderApi.deploy).toHaveBeenCalledWith("sess-123"));
    await waitFor(() => expect(useOnboardingStore.getState().firstAgentSession).toBe("sess-123"));
    await waitFor(() => expect(screen.getByText(/готово/i)).toBeInTheDocument());
  });

  it("partial extract → does NOT claim success and does not deploy", async () => {
    vi.mocked(builderApi.extract).mockResolvedValue({
      complete: false,
      session_id: "sess-partial",
      step: 1,
      total_steps: 3,
      questions: ["q1", "q2", "q3"],
      next_question: "q2",
      partial_spec: { name: "x", description: "x", type: "skill", template: "tracker", config: {} },
    } as never);

    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByText(/чашки кофе/i));

    await waitFor(() => expect(builderApi.extract).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/допиши детали/i)).toBeInTheDocument());
    expect(builderApi.deploy).not.toHaveBeenCalled();
    expect(screen.queryByText(/готово/i)).not.toBeInTheDocument();
  });

  it("shows a human RU message when the builder rejects (no raw errors)", async () => {
    vi.mocked(builderApi.extract).mockRejectedValue(new Error("builder offline"));
    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByText(/дневник настроения/i));
    await waitFor(() =>
      expect(screen.getByText(/не получилось создать/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/builder offline/i)).not.toBeInTheDocument();
  });

  it("skip button advances without creating an agent", async () => {
    const user = userEvent.setup();
    render(<FirstAgentStep />);
    await user.click(screen.getByRole("button", { name: /пропустить/i }));
    expect(useOnboardingStore.getState().currentStep).not.toBe("first-agent");
    expect(builderApi.extract).not.toHaveBeenCalled();
  });
});
