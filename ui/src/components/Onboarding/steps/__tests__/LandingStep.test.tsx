import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { LandingStep } from "../LandingStep";
import { api } from "../../../../api/client";

vi.mock("../../../../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
  },
}));

describe("LandingStep", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("persists onboarding_completed on mount", async () => {
    render(<LandingStep />);
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({
        onboarding_completed: true,
      }),
    );
  });
});
