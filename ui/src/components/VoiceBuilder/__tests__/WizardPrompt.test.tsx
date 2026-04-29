// ui/src/components/VoiceBuilder/__tests__/WizardPrompt.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WizardPrompt } from "../WizardPrompt";

vi.mock("../../../api/builder", () => ({
  builderApi: { say: vi.fn().mockResolvedValue({ status: "ok", duration: 1.5 }) },
}));

describe("WizardPrompt", () => {
  it("renders the question and step counter", () => {
    render(<WizardPrompt question="Какая дневная цель?" step={1} totalSteps={3} onTtsDone={() => {}} />);
    expect(screen.getByText(/Какая дневная цель/)).toBeInTheDocument();
    expect(screen.getByText(/Шаг 2 из 3/)).toBeInTheDocument();
  });

  it("calls say() on mount and onTtsDone after it resolves", async () => {
    const { builderApi } = await import("../../../api/builder");
    const done = vi.fn();
    render(<WizardPrompt question="Какая дневная цель?" step={0} totalSteps={3} onTtsDone={done} />);

    await waitFor(() => expect(builderApi.say).toHaveBeenCalledWith("Какая дневная цель?", "ru"));
    await waitFor(() => expect(done).toHaveBeenCalled());
  });
});
