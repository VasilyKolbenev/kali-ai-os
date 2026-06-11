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
    localStorage.clear();
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

  it("gated=true when a live backend says onboarding incomplete", async () => {
    vi.mocked(api.settings).mockResolvedValue({});
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.gated).toBe(true);
  });

  it("keeps loading on fetch failure instead of re-gating a booting kernel", async () => {
    // A cold backend boots models for 40-60s; falling back to the wizard
    // re-asks a returning user for their API key against a dead kernel.
    vi.mocked(api.settings).mockRejectedValue(new Error("net"));
    const { result } = renderHook(() => useOnboardingGate());
    await new Promise((r) => setTimeout(r, 150));
    expect(result.current.loading).toBe(true);
  });

  it("recovers from early failures once the backend comes up", async () => {
    vi.mocked(api.settings)
      .mockRejectedValueOnce(new Error("booting"))
      .mockResolvedValue({ onboarding_completed: true });
    const { result } = renderHook(() => useOnboardingGate());
    await waitFor(
      () => expect(result.current.loading).toBe(false),
      { timeout: 4000 },
    );
    expect(result.current.gated).toBe(false);
  });

  it("skips the gate for a returning user even while the kernel is down", async () => {
    useOnboardingStore.setState({ completed: true });
    vi.mocked(api.settings).mockRejectedValue(new Error("net"));
    const { result } = renderHook(() => useOnboardingGate());
    expect(result.current.loading).toBe(false);
    expect(result.current.gated).toBe(false);
  });
});
