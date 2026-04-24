import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VoiceSettings } from "../VoiceSettings";
import { api } from "../../../../api/client";

vi.mock("../../../../api/client", () => ({
  api: {
    config: vi.fn(),
    updateConfig: vi.fn(),
  },
}));

function seed(overrides: Partial<Record<string, unknown>> = {}) {
  vi.mocked(api.config).mockResolvedValue({
    voice: {
      wake_word: "jarvis",
      mode: "wake_word",
      auto_start: false,
      ...overrides,
    },
  });
}

describe("VoiceSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.updateConfig).mockResolvedValue({
      voice: { wake_word: "jarvis", mode: "wake_word", auto_start: false },
    });
  });

  it("renders current voice values from /config", async () => {
    seed({ wake_word: "kali", mode: "push_to_talk", auto_start: true });
    render(<VoiceSettings />);
    await waitFor(() => {
      expect(screen.getByLabelText(/wake word/i)).toHaveValue("kali");
    });
    expect(screen.getByRole("button", { name: /кнопка/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByRole("switch", { name: /автостарт/i }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("apply button is disabled until a field changes", async () => {
    seed();
    render(<VoiceSettings />);
    const apply = await screen.findByRole("button", { name: /применить/i });
    expect(apply).toBeDisabled();

    const user = userEvent.setup();
    const input = await screen.findByLabelText(/wake word/i);
    await user.clear(input);
    await user.type(input, "kali");
    expect(apply).not.toBeDisabled();
  });

  it("toggles auto_start when the switch is clicked", async () => {
    seed();
    const user = userEvent.setup();
    render(<VoiceSettings />);
    const toggle = await screen.findByRole("switch", { name: /автостарт/i });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("save calls api.updateConfig with the voice subtree only", async () => {
    seed();
    const user = userEvent.setup();
    render(<VoiceSettings />);
    const input = await screen.findByLabelText(/wake word/i);
    await user.clear(input);
    await user.type(input, "kali");
    await user.click(screen.getByRole("button", { name: /кнопка/i }));
    await user.click(screen.getByRole("switch", { name: /автостарт/i }));
    await user.click(screen.getByRole("button", { name: /применить/i }));

    await waitFor(() => expect(api.updateConfig).toHaveBeenCalledTimes(1));
    expect(api.updateConfig).toHaveBeenCalledWith({
      voice: {
        wake_word: "kali",
        mode: "push_to_talk",
        auto_start: true,
      },
    });
  });

  it("rejects empty wake_word without calling api", async () => {
    seed();
    const user = userEvent.setup();
    render(<VoiceSettings />);
    const input = await screen.findByLabelText(/wake word/i);
    await user.clear(input);
    await user.type(input, "   ");
    await user.click(screen.getByRole("button", { name: /применить/i }));
    await waitFor(() =>
      expect(screen.getByText(/не может быть пустым/i)).toBeInTheDocument(),
    );
    expect(api.updateConfig).not.toHaveBeenCalled();
  });

  it("shows restart hint after successful save", async () => {
    seed();
    const user = userEvent.setup();
    render(<VoiceSettings />);
    const input = await screen.findByLabelText(/wake word/i);
    await user.clear(input);
    await user.type(input, "kali");
    await user.click(screen.getByRole("button", { name: /применить/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/применятся при следующем запуске/i),
      ).toBeInTheDocument(),
    );
  });
});
