import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { NumberReveal } from "../NumberReveal";

describe("NumberReveal", () => {
  it("displays final value immediately when prefers-reduced-motion", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: q.includes("reduce"),
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    render(<NumberReveal value={42} />);
    expect(screen.getByTestId("number-reveal")).toHaveTextContent("42");
  });

  it("eventually reaches the target value", async () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: false,
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    render(<NumberReveal value={100} durationMs={100} />);
    await waitFor(() => {
      expect(screen.getByTestId("number-reveal")).toHaveTextContent("100");
    }, { timeout: 2000 });
  });
});
