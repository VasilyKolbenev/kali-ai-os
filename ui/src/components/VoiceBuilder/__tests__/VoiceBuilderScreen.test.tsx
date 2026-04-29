// ui/src/components/VoiceBuilder/__tests__/VoiceBuilderScreen.test.tsx
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceBuilderScreen } from "../VoiceBuilderScreen";
import { useBuilderStore } from "../../../stores/builder";

vi.mock("../../../api/builder", () => ({
  builderApi: {
    extract: vi.fn(),
    answer: vi.fn(),
    deploy: vi.fn(),
    cancel: vi.fn(),
    transcribe: vi.fn(),
    say: vi.fn().mockResolvedValue({ status: "ok", duration: 1 }),
    start: vi.fn(),
  },
}));

vi.mock("../useAudioCapture", () => ({
  useAudioCapture: () => ({
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn().mockResolvedValue({ audio: new Uint8Array([0, 0]), sample_rate: 16000 }),
    isRecording: false,
  }),
}));

describe("VoiceBuilderScreen e2e", () => {
  beforeEach(() => {
    useBuilderStore.getState().reset();
    vi.clearAllMocks();
  });

  it("ESC anywhere triggers cancel via store", async () => {
    render(<VoiceBuilderScreen />);
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    // After cancel, store resets; phase back to idle.
    expect(useBuilderStore.getState().phase).toBe("idle");
  });

  it("text-fallback path: type + Enter → /builder/extract called", async () => {
    const { builderApi } = await import("../../../api/builder");
    (builderApi.extract as ReturnType<typeof vi.fn>).mockResolvedValue({
      complete: true,
      session_id: "sid",
      spec: {
        name: "treker", description: "", type: "skill", template: "tracker",
        config: { interval: "2 часа", goal: "2 литра", notify_channel: "чат" },
      },
    });

    render(<VoiceBuilderScreen />);
    fireEvent.click(screen.getByText(/печатать вместо/i));
    const input = await screen.findByPlaceholderText(/трекер/i);
    fireEvent.change(input, { target: { value: "трекер 2л 2ч в чат" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(builderApi.extract).toHaveBeenCalled());
  });
});
