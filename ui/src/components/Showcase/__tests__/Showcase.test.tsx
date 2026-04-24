import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Showcase } from "../Showcase";

describe("Showcase", () => {
  it("renders section headings for tokens / motion / hud", () => {
    render(<Showcase />);
    expect(screen.getByText(/colors/i)).toBeInTheDocument();
    expect(screen.getByText(/motion/i)).toBeInTheDocument();
    expect(screen.getByText(/hud primitives/i)).toBeInTheDocument();
  });

  it("mounts at least one PulseOrb", () => {
    render(<Showcase />);
    expect(screen.getAllByTestId("pulse-orb").length).toBeGreaterThan(0);
  });
});
