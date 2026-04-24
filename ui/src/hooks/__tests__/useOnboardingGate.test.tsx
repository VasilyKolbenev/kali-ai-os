import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useOnboardingGate } from "../useOnboardingGate";
import { api } from "../../api/client";
import { useOnboardingStore } from "../../stores/onboardingStore";

vi.mock("../../api/client", () => ({
  api: { settings: vi.fn() },
}));

describe("useOnboardingGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOnboardingStore.setState({
      currentStep: "welcome",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
    });
  });

  it("returns loading initially, then gated=false when settings say completed", async () => {
    vi.mocked(api.settings).mockResolvedValue({ onboarding_completed: true });
    const { result } = renderHook(() => useOnboardingGate());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(false);
  });

  it("gated=true when onboarding_completed is false or absent", async () => {
    vi.mocked(api.settings).mockResolvedValue({});
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(true);
  });

  it("falls back to gated=true on fetch failure (safer default)", async () => {
    vi.mocked(api.settings).mockRejectedValue(new Error("net"));
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(true);
  });
});
