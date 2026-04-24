import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PulseOrb } from "../../hud";

describe("prefers-reduced-motion", () => {
  it("disables PulseOrb animation when user prefers reduced motion", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: q.includes("reduce"),
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    const { getByTestId } = render(<PulseOrb />);
    const orb = getByTestId("pulse-orb");
    expect(orb.style.animation).toBe("none");
  });
});
