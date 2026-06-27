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
    getCapabilities: vi.fn(),
    loadAgent: vi.fn(),
    unloadAgent: vi.fn(),
    revokeAgent: vi.fn(),
    agentConsents: vi.fn(),
    skillInstall: vi.fn(),
    skillUninstall: vi.fn(),
    skillPublish: vi.fn(),
    skillsCatalogSources: vi.fn(),
    skillsCatalogList: vi.fn(),
    skillsCatalogRefresh: vi.fn(),
    agentConfigStatus: vi.fn(),
    // Community (merged feed) + social + magic-link
    catalogCommunity: vi.fn(),
    catalogCommunityInstall: vi.fn(),
    catalogLike: vi.fn(),
    catalogUnlike: vi.fn(),
    catalogRate: vi.fn(),
    catalogComments: vi.fn(),
    catalogComment: vi.fn(),
    communityMagicLink: vi.fn(),
    communityVerify: vi.fn(),
  },
}));

/** A minimal merged community card (UGC) for the feed tests. */
function ugcCard(over: Partial<import("../../../api/types").CommunityCard> = {}) {
  return {
    source: "ugc" as const,
    slug: "weather-bot",
    name: "weather-bot",
    description: "Погода голосом",
    category: null,
    version: "1.0.0",
    creator_id: null,
    creator_handle: "vasily",
    install_count: 0,
    like_count: 2,
    rating_count: 0,
    avg_rating: 0,
    liked: false,
    rated: null,
    installed: false,
    source_id: null,
    trust: "community",
    ...over,
  };
}

describe("AgentStore (Мастерская)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.skillsInstalled).mockResolvedValue({ results: [], count: 0 });
    vi.mocked(api.agents).mockResolvedValue([
      { name: "weather", description: "Weather agent" },
    ] as never);
    vi.mocked(api.runningAgents).mockResolvedValue([] as never);
    vi.mocked(api.skillsCatalogList).mockRejectedValue(new Error("offline"));
    vi.mocked(api.catalogCommunity).mockRejectedValue(new Error("offline"));
    vi.mocked(api.agentConfigStatus).mockResolvedValue({});
    vi.mocked(api.agentConsents).mockResolvedValue({});
    // Default: not sensitive → one-click enable stays (weather/currency).
    vi.mocked(api.getCapabilities).mockResolvedValue({
      name: "weather",
      capabilities: [{ id: "network:http", label: "Выходить в интернет", risk: "low" }],
      sensitive: false,
    });
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

  it("sensitive agent: Включить → consent disclosure → Разрешить enables", async () => {
    vi.mocked(api.agents).mockResolvedValue([
      { name: "email", description: "Email agent" },
    ] as never);
    vi.mocked(api.getCapabilities).mockResolvedValue({
      name: "email",
      capabilities: [
        { id: "email:send", label: "Отправлять письма от твоего имени", risk: "high" },
        { id: "email:read", label: "Читать твою почту", risk: "med" },
      ],
      sensitive: true,
    });
    vi.mocked(api.runningAgents)
      .mockResolvedValueOnce([] as never)
      .mockResolvedValue([{ name: "email" }] as never);
    vi.mocked(api.loadAgent).mockResolvedValue({ status: "ok" });

    const user = userEvent.setup();
    render(<AgentStore />);

    const card = (await screen.findByText("Почта")).closest(".glass") as HTMLElement;
    await user.click(await waitFor(() => {
      const btn = [...card.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Включить"),
      );
      if (!btn) throw new Error("enable button not rendered yet");
      return btn;
    }));

    // Disclosure appears with the «…от твоего имени» phrasing; no enable yet.
    await waitFor(() =>
      expect(screen.getByText("Отправлять письма от твоего имени")).toBeInTheDocument(),
    );
    expect(api.loadAgent).not.toHaveBeenCalled();

    await user.click(screen.getByText("Разрешить"));
    await waitFor(() => expect(api.loadAgent).toHaveBeenCalledWith("email"));
  });

  it("sensitive agent: Не сейчас cancels without enabling", async () => {
    vi.mocked(api.agents).mockResolvedValue([
      { name: "email", description: "Email agent" },
    ] as never);
    vi.mocked(api.getCapabilities).mockResolvedValue({
      name: "email",
      capabilities: [
        { id: "email:send", label: "Отправлять письма от твоего имени", risk: "high" },
      ],
      sensitive: true,
    });

    const user = userEvent.setup();
    render(<AgentStore />);

    const card = (await screen.findByText("Почта")).closest(".glass") as HTMLElement;
    await user.click(await waitFor(() => {
      const btn = [...card.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Включить"),
      );
      if (!btn) throw new Error("enable button not rendered yet");
      return btn;
    }));

    await user.click(await screen.findByText("Не сейчас"));
    await waitFor(() =>
      expect(screen.queryByText("Отправлять письма от твоего имени")).not.toBeInTheDocument(),
    );
    expect(api.loadAgent).not.toHaveBeenCalled();
  });

  it("Мои: Отозвать доступ → revokeAgent → «Доступ отозван» (M2.2)", async () => {
    vi.mocked(api.agents).mockResolvedValue([
      { name: "email", description: "Email agent" },
    ] as never);
    vi.mocked(api.runningAgents).mockResolvedValue([{ name: "email" }] as never);
    vi.mocked(api.agentConsents)
      .mockResolvedValueOnce({}) // bootstrap: granted (no revoke on record)
      .mockResolvedValue({ email: "revoked" }); // after revoke
    vi.mocked(api.revokeAgent).mockResolvedValue({ status: "revoked", agent: "email" });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Мои"));

    const card = (await screen.findByText("Почта")).closest(".glass") as HTMLElement;
    expect(card.textContent).toContain("Работает");

    await user.click(await waitFor(() => {
      const btn = [...card.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Отозвать доступ"),
      );
      if (!btn) throw new Error("revoke button not rendered yet");
      return btn;
    }));

    await waitFor(() => expect(api.revokeAgent).toHaveBeenCalledWith("email"));
    await waitFor(() => expect(card.textContent).toContain("Доступ отозван"));
  });

  it("Мои: revoked агент → Разрешить снова → loadAgent → «Работает» (M2.2)", async () => {
    vi.mocked(api.agents).mockResolvedValue([
      { name: "email", description: "Email agent" },
    ] as never);
    vi.mocked(api.runningAgents).mockResolvedValue([{ name: "email" }] as never);
    vi.mocked(api.agentConsents)
      .mockResolvedValueOnce({ email: "revoked" }) // bootstrap: previously revoked
      .mockResolvedValue({ email: "approved" }); // after re-enable
    vi.mocked(api.loadAgent).mockResolvedValue({ status: "ok" });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Мои"));

    const card = (await screen.findByText("Почта")).closest(".glass") as HTMLElement;
    expect(card.textContent).toContain("Доступ отозван");

    await user.click(await waitFor(() => {
      const btn = [...card.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Разрешить снова"),
      );
      if (!btn) throw new Error("re-enable button not rendered yet");
      return btn;
    }));

    await waitFor(() => expect(api.loadAgent).toHaveBeenCalledWith("email"));
    await waitFor(() => expect(card.textContent).toContain("Работает"));
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

  it("Сообщество renders merged cards from the merged endpoint", async () => {
    vi.mocked(api.catalogCommunity).mockResolvedValue({
      results: [
        ugcCard({ slug: "weather-bot", name: "weather-bot" }),
        {
          ...ugcCard({ slug: "", name: "pdf-skill" }),
          source: "curated" as const,
          source_id: "kali",
          creator_handle: "anthropics",
        },
      ],
      count: 2,
    });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Сообщество"));

    // Both the UGC and the curated card surface; the merged endpoint was used.
    await waitFor(() => expect(screen.getByText("weather-bot")).toBeInTheDocument());
    expect(screen.getByText("pdf-skill")).toBeInTheDocument();
    expect(api.catalogCommunity).toHaveBeenCalled();
  });

  it("Сообщество: degrades to curated-only when the UGC source is empty (no error wall)", async () => {
    // Mirrors the backend merge: Supabase offline → only curated cards present.
    vi.mocked(api.catalogCommunity).mockResolvedValue({
      results: [
        {
          ...ugcCard({ slug: "", name: "curated-only" }),
          source: "curated" as const,
          source_id: "kali",
        },
      ],
      count: 1,
    });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Сообщество"));

    await waitFor(() => expect(screen.getByText("curated-only")).toBeInTheDocument());
    // No "Стань первым" empty wall and no raw error text.
    expect(screen.queryByText(/Стань первым/)).not.toBeInTheDocument();
    expect(screen.queryByText(/offline/)).not.toBeInTheDocument();
  });

  it("Сообщество: like button calls the like endpoint + updates count optimistically", async () => {
    vi.mocked(api.catalogCommunity).mockResolvedValue({
      results: [ugcCard({ like_count: 2, liked: false })],
      count: 1,
    });
    // Resolve slowly so we can observe the optimistic update before it settles.
    vi.mocked(api.catalogLike).mockResolvedValue({ status: "ok", liked: true });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Сообщество"));

    const likeBtn = await screen.findByLabelText("Нравится");
    expect(likeBtn.textContent).toContain("2");
    await user.click(likeBtn);

    // Optimistic: count bumps to 3 immediately and the endpoint is hit.
    await waitFor(() => expect(likeBtn.textContent).toContain("3"));
    expect(api.catalogLike).toHaveBeenCalledWith("weather-bot");
  });

  it("Сообщество: rating while signed-out shows the magic-link prompt (not a fake success)", async () => {
    vi.mocked(api.catalogCommunity).mockResolvedValue({
      results: [ugcCard()],
      count: 1,
    });
    vi.mocked(api.catalogRate).mockResolvedValue({ status: "sign-in required" });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Сообщество"));

    const rateBtn = await screen.findByLabelText("Оценить на 4");
    await user.click(rateBtn);

    // The honest sign-in prompt surfaces — KALI magic-link, no OAuth button.
    await waitFor(() =>
      expect(screen.getByText("Войти в KALI")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Прислать ссылку для входа/)).toBeInTheDocument();
    // No Google/Apple OAuth BUTTON anywhere (the copy may reassure that we do
    // NOT use them, but there must be no clickable OAuth affordance).
    const buttons = screen.getAllByRole("button");
    expect(
      buttons.some((b) => /войти через|sign in with|google|apple/i.test(b.textContent || "")),
    ).toBe(false);
  });

  it("Сообщество: comment while signed-out shows the magic-link prompt", async () => {
    vi.mocked(api.catalogCommunity).mockResolvedValue({
      results: [ugcCard()],
      count: 1,
    });
    vi.mocked(api.catalogComments).mockResolvedValue({ comments: [] });
    vi.mocked(api.catalogComment).mockResolvedValue({ status: "sign-in required" });

    const user = userEvent.setup();
    render(<AgentStore />);
    await user.click(screen.getByText("Сообщество"));

    await user.click(await screen.findByText("Отзывы"));
    const input = await screen.findByPlaceholderText("Оставить отзыв…");
    await user.type(input, "Класс");
    await user.click(screen.getByLabelText("Отправить отзыв"));

    await waitFor(() =>
      expect(screen.getByText("Войти в KALI")).toBeInTheDocument(),
    );
  });
});
