import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Settings } from "../Settings";
import { api } from "../../../api/client";

// Child sections own their own behaviour + tests; stub them so this suite
// isolates the LLM-picker save path (the WS-2 #2.5 fix).
vi.mock("../sections/VoiceSettings", () => ({ VoiceSettings: () => null }));
vi.mock("../sections/ProfileSettings", () => ({ ProfileSettings: () => null }));
vi.mock("../sections/AdvancedSettings", () => ({ AdvancedSettings: () => null }));

vi.mock("../../../api/client", () => ({
  api: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    updateConfig: vi.fn(),
    testApiKey: vi.fn(),
  },
}));

function seed() {
  vi.mocked(api.settings).mockResolvedValue({
    llm: {
      provider: "openai",
      openai_key: "",
      openai_model: "gpt-4.1-mini",
      anthropic_key: "",
      anthropic_model: "claude-sonnet-4-20250514",
      google_key: "",
      google_model: "gemini-3.1-pro",
      deepseek_key: "",
      deepseek_model: "deepseek-v3.2",
    },
    language: "ru",
  });
}

describe("Settings — LLM provider/model picker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.updateConfig).mockResolvedValue({});
    vi.mocked(api.updateSettings).mockResolvedValue({});
    seed();
  });

  it("save writes the active provider+model to the config (PATCH /config)", async () => {
    const user = userEvent.setup();
    render(<Settings />);

    // Switch provider OpenAI -> Anthropic, then pick an Anthropic model.
    const anthropicProvider = await screen.findByRole("button", {
      name: /^anthropic$/i,
    });
    await user.click(anthropicProvider);
    await user.click(
      screen.getByRole("button", { name: "claude-opus-4-20250414" }),
    );

    await user.click(screen.getByRole("button", { name: /^сохранить$/i }));

    // The router's source of truth (config.llm) must receive the new pick.
    await waitFor(() => expect(api.updateConfig).toHaveBeenCalledTimes(1));
    expect(api.updateConfig).toHaveBeenCalledWith({
      llm: {
        cloud_provider: "anthropic",
        cloud_model: "claude-opus-4-20250414",
      },
    });
  });

  it("save still persists API keys via POST /settings (env)", async () => {
    const user = userEvent.setup();
    render(<Settings />);

    await user.click(await screen.findByRole("button", { name: /^сохранить$/i }));

    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.updateSettings).mock.calls[0][0];
    // keys/models still flow to env as before; provider echoed too
    expect(payload).toMatchObject({ provider: "openai" });
    expect(payload).toHaveProperty("anthropic_key");
    expect(payload).toHaveProperty("language", "ru");
  });
});
