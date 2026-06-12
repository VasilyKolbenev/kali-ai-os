import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentStore } from "../AgentStore";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({
  api: {
    skillsInstalled: vi.fn(),
    agents: vi.fn(),
    runningAgents: vi.fn(),
    loadAgent: vi.fn(),
    unloadAgent: vi.fn(),
    skillInstall: vi.fn(),
    skillUninstall: vi.fn(),
    skillPublish: vi.fn(),
    skillsCatalogSources: vi.fn(),
    skillsCatalogList: vi.fn(),
    skillsCatalogRefresh: vi.fn(),
  },
}));

describe("AgentStore (Мастерская)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.skillsInstalled).mockResolvedValue({ results: [], count: 0 });
    vi.mocked(api.agents).mockResolvedValue([
      { name: "weather", description: "Weather agent" },
    ] as never);
    vi.mocked(api.runningAgents).mockResolvedValue([] as never);
    vi.mocked(api.skillsCatalogList).mockRejectedValue(new Error("offline"));
  });

  it("renders the header and the three loop segments", async () => {
    render(<AgentStore />);
    expect(screen.getByText("Мастерская")).toBeInTheDocument();
    expect(screen.getByText("Мои")).toBeInTheDocument();
    expect(screen.getByText("Витрина")).toBeInTheDocument();
    expect(screen.getByText("Сообщество")).toBeInTheDocument();
  });

  it("enables a curated agent: Включить → loadAgent → Работает", async () => {
    vi.mocked(api.runningAgents)
      .mockResolvedValueOnce([] as never) // bootstrap: nothing running
      .mockResolvedValue([{ name: "weather" }] as never); // after enable
    vi.mocked(api.loadAgent).mockResolvedValue({ status: "ok" });

    const user = userEvent.setup();
    render(<AgentStore />);

    const card = (await screen.findByText("Погода")).closest(".glass") as HTMLElement;
    expect(card).toBeTruthy();
    await user.click(await waitFor(() => {
      const btn = [...card.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Включить"),
      );
      if (!btn) throw new Error("enable button not rendered yet");
      return btn;
    }));

    await waitFor(() => expect(api.loadAgent).toHaveBeenCalledWith("weather"));
    await waitFor(() =>
      expect(card.textContent).toContain("Работает"),
    );
  });

  it("Мои with nothing enabled shows the friendly empty state", async () => {
    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Мои"));
    await waitFor(() =>
      expect(screen.getByText(/Пока пусто/)).toBeInTheDocument(),
    );
  });

  it("Сообщество degrades gracefully when the catalog is unreachable", async () => {
    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Сообщество"));
    await waitFor(() =>
      expect(screen.getByText(/Стань первым/)).toBeInTheDocument(),
    );
    // No raw error text leaks to the user
    expect(screen.queryByText(/offline/)).not.toBeInTheDocument();
  });
});
